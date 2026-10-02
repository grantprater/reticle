r"""The spike: its glyph on the minimap and its marker on the ally roster.

    .\.venv\Scripts\python.exe -m reticle spike <session> | --all

Owns [owns:spike-observation].

Until this module no channel read the spike [domain:minimap/no-spike-channel],
so a self or ally fit that landed on the glyph survived every gate that asks
about a read confuser. This reader measures three things from the lossless
crop caches and decodes no video (`reticle spike` walks the caches in
`cli._spike_session` and hands each crop to `read_frame` and
`roster_marker`); `adjudication.spike_carrier` cross-checks them, and
`on_glyph` is the refusal the icon fits ask.

**The minimap glyph, fitted as a shape.** The glyph is a rounded equilateral
triangle holding a black circle and dots [domain:minimap/spike-glyph], yellow
in every state, base down on the ground and base up when carried
[domain:minimap/spike-inversion]. The fit is a normalised cross-correlation of
a rendered triangle (`glyph_template`) against the crop's yellowness, min(R, G) - B,
at three sides per orientation, plus the fitted amplitude: the yellowness step
the template explains. The correlation alone admits noise, since it ignores
scale, and the pale self ring correlates at 0.6-0.75; the amplitude separates
them because the glyph is a saturated yellow and the ring is not. Yellowness
is chroma, so under 4:2:0 [domain:capture/chroma-420] it arrives in 2x2
blocks and the dots are not resolved; the silhouette and the dark circle are.
A fit whose correlation or amplitude falls short of the gate is kept as a
`candidate` with its reason, never dropped.

Measured before the gate was set (2026-09-28, 250 labelled fits on
c40d950031bb and 5822b6646448, the fits every 0.6+ correlation peak):
glyph peaks cluster at correlation 0.78-0.89 with amplitude 100-140, and
every one of 32 sampled from that cluster was a spike by eye; the pale self
ring and partial glyphs fill 0.6-0.78 at amplitude 40-95. A glyph a portrait
half covers reads 0.72-0.81 at amplitude 77-81, which the strong-correlation
arm of the gate admits at 0.78 and loses below it.

**The carried glyph belongs to the icon it sits under.** The player
(2026-09-28): a teammate's carried spike draws at the lower left of that
teammate's icon, over it [domain:minimap/spike-carrier-overlay]. So a carried
glyph's owner is the icon above and to its right. A fit centred on the glyph
itself, or near it while another icon holds the carrier's place, is the
glyph; a fit that may be the carrier is kept (`on_glyph`).

**The roster marker, fitted as a template.** The ally roster marks the
carrier [domain:hud/spike-carrier-marker]: a white badge holding the glyph,
below the carrier's health pill. The `hud_roster` ROI clips it after its top
ten rows, which carry the badge's rim and the glyph's upper half; the stored
template (`templates/valorant-16x9-spike-marker.npz`) is the mean of 30 such
crops. Its left edge sits at column 11 + 66 k of the 1080p crop for slot k,
which is not the equal fifths `roster.slot_detail` splits the bar into; over
four sessions a match above 0.8 peaked only at those five columns and never
twice in one frame, so the gate reads the match only there. The slot is the bar's PACKED position: survivors pack toward the
scoreline, so a slot index is not a teammate until the lineup binds it, and
this module names nobody.

**A widget drawn turned over.** A variant widget (`widget_frame`) may draw the
map turned 180 degrees, as a side-based minimap does in one half, and the
reader meets it resampled into the baked frame, turned back. The spike glyph
and the portraits stay upright on the screen while the map turns
[domain:minimap/upright-icons-on-turned-map], so in the baked frame they
arrive upside down: a dropped glyph (base down on the screen) is base up, and
a carrier's icon sits below and to the left of its glyph rather than above
and to the right. `rotation` (the placement's, `WidgetFrame.at`) turns the
orientation test and the carrier's offset with it. On the Iso capture
4f207c0c4e39, whose first half draws the widget turned over, spike-0.1.0 read
every dropped glyph of that half as carried; refitted upright, eight of eight
sampled read dropped at a higher correlation (docs/ISO_SPIKE_CARRIER.md).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .version import SPIKE_VERSION

#: Triangle sides tried, in widget px at scale 1.0 (`minimap.widget_scale`).
#: The ground glyph is the larger [domain:minimap/spike-inversion]; best fits
#: on 5822b6646448 were 24 (ground) and 18 (carried).
SIDES = {"dropped": (18.0, 21.0, 24.0), "carried": (15.0, 17.5, 20.0)}
#: The accept gate: correlation and amplitude (yellowness levels), or a strong
#: correlation at a lower amplitude for a glyph a portrait partly covers.
NCC_MIN, AMP_MIN = 0.70, 95.0
NCC_STRONG, AMP_PARTIAL = 0.78, 75.0
#: The glyph's yellow is greenish: over its keyed pixels R - G read -25 to
#: -15 on 120 accepted glyphs of 5822b6646448. An orange glyph inside a dark
#: disc (409.1 s there: the spike Gekko's Wingman just planted, drawn inside
#: Wingman's icon [domain:abilities/gekko-wingman-plant-minimap]) read +25
#: at the same correlation, so a fit redder than this is `orange`, kept as a
#: candidate.
RG_MAX = 5.0
#: Below this a peak is not stored at all, even as a candidate.
NCC_CANDIDATE, AMP_CANDIDATE = 0.60, 60.0
#: Yellowness a pixel needs to seed a search window around it.
SEED_Y = 60
#: Two peaks closer than this (scale 1.0 px) are one glyph.
NMS_PX = 10.0

#: `carrier_offset`: the carrier's icon centre relative to its carried glyph,
#: scale 1.0 px, and how far an icon may sit from that point. Median of the
#: ally fits beside accepted carried glyphs at 0.5 Hz: (7, -8) over 100 on
#: 5822b6646448 and (7, -7) over 35 on c40d950031bb, most within 2 px.
CARRIER_DX, CARRIER_DY, CARRIER_TOL_PX = 7.0, -7.5, 4.5
#: `on_glyph`: a fit within this of a glyph's centroid (scale 1.0 px) may land
#: on it: about the carried glyph's inradius plus the fit error. The spike fits
#: of the self-fit labels sat 4.0-5.0 px from the glyph; a self icon beside a
#: glyph it does not carry, 7.9.
ON_GLYPH_PX = 6.5
#: A fit centred this near a glyph's centroid (scale 1.0 px) rings the glyph
#: itself, whatever carries it. The ally fits the player called spike sat 0-2.8
#: px from it; the nearest ones he called an agent, 3.1 and 4.1.
CORE_PX = 3.0
#: Two fits nearer than this (scale 1.0 px) are one icon: twice `FIT_ERR_PX`.
SAME_ICON_PX = 4.0

#: The roster marker: template rows searched, first column, slot pitch, gate.
#: The gate reads the match only at the five columns. On 5822b6646448 the
#: best of them reached 0.9+ on 357 of 371 frames the minimap read a carried
#: glyph, and 0.60-0.9 on 13 more, where a bright scene behind the bar washes
#: out the badge's rim; on frames without a carried glyph it stayed under 0.55
#: but for 2 (and 16 at 0.9+, the glyph hidden under a stack of icons). A gate
#: at 0.60 read a marker at 0.602 on a defending round (1943.5 s) where the
#: crop shows none, so it sits at 0.65.
MARK_ROWS = (64, 78)
MARK_X0, MARK_PITCH = 11, 66
MARK_NCC_MIN = 0.65
#: The roster crop height the marker geometry was measured on (1080p).
ROSTER_H = 78

TEMPLATE_FILE = Path(__file__).parent / "templates" / "valorant-16x9-spike-marker.npz"


def spike_yellowness(crop: np.ndarray) -> np.ndarray:
    """min(R, G) - B, clipped at 0: the spike's saturated yellow is high,
    grey floor and teal are near 0."""
    b, g, r = (c.astype(np.int16) for c in cv2.split(crop))
    return np.clip(np.minimum(r, g) - b, 0, 255).astype(np.float32)


@lru_cache(maxsize=64)
def glyph_template(side: float, base_down: bool, margin: int = 3) -> np.ndarray:
    """The glyph's yellowness model: 1 inside a rounded equilateral triangle
    of `side` px, 0 on its black circle and outside, rendered 8x and area-
    averaged. The centre pixel is the triangle's centroid."""
    ss = 8
    h = side * np.sqrt(3) / 2
    half = int(np.ceil(max(side / 2, 2 * h / 3))) + margin
    n = (2 * half + 1) * ss
    c = n / 2
    pts = np.array([(0.0, -2 * h / 3), (-side / 2, h / 3), (side / 2, h / 3)])
    if not base_down:
        pts[:, 1] *= -1
    rr = side * 0.14 * ss                       # corner rounding radius
    circum = np.linalg.norm(pts[0])
    poly = (pts * (1 - 2 * rr / ss / circum) * ss + c).astype(np.int32)
    img = np.zeros((n, n), np.uint8)
    cv2.fillPoly(img, [poly], 255)
    k = int(2 * rr) | 1
    img = cv2.dilate(img, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cv2.circle(img, (int(c), int(c)), int(side * 0.22 * ss), 0, int(max(1, side * 0.07 * ss)))
    return cv2.resize(img.astype(np.float32) / 255, (n // ss, n // ss),
                      interpolation=cv2.INTER_AREA)


def _base_down(state: str, rotation: int = 0) -> bool:
    """Whether a glyph in `state` points its base down in the baked frame: on
    the screen a dropped glyph is base down, and a widget drawn turned over
    (`rotation` 180) arrives turned back, the glyph with it."""
    return (state == "dropped") != (int(rotation) % 360 == 180)


def _fit(y: np.ndarray, sc: float, rotation: int = 0):
    """Per state, the best correlation, its amplitude and side at every pixel
    of `y` (-1 where the window does not fit)."""
    y2 = y * y
    out = {}
    for state, sides in SIDES.items():
        best = None
        for s in sides:
            t = glyph_template(round(s * sc, 2), _base_down(state, rotation))
            if t.shape[0] > y.shape[0] or t.shape[1] > y.shape[1]:
                continue
            ncc = cv2.matchTemplate(y, t, cv2.TM_CCOEFF_NORMED)
            k = np.full_like(t, 1.0 / t.size)
            mu = cv2.matchTemplate(y, k, cv2.TM_CCORR)
            sd = np.sqrt(np.maximum(cv2.matchTemplate(y2, k, cv2.TM_CCORR) - mu * mu, 0))
            amp = ncc * sd / float(t.std())
            p = t.shape[0] // 2
            pad = ((p, y.shape[0] - ncc.shape[0] - p), (p, y.shape[1] - ncc.shape[1] - p))
            ncc = np.pad(ncc, pad, constant_values=-1)
            amp = np.pad(amp, pad)
            if best is None:
                best = [ncc, amp, np.full(y.shape, s, np.float32)]
            else:
                w = ncc > best[0]
                best = [np.where(w, ncc, best[0]), np.where(w, amp, best[1]),
                        np.where(w, s, best[2])]
        out[state] = best
    return out


def glyph_gate(ncc: float, amp: float) -> str | None:
    """None where a glyph fit is accepted, else why not."""
    if (ncc >= NCC_MIN and amp >= AMP_MIN) or (ncc >= NCC_STRONG and amp >= AMP_PARTIAL):
        return None
    return "weak_correlation" if ncc < NCC_MIN else "weak_amplitude"


def glyph_fits(crop: np.ndarray, support: np.ndarray | None = None,
               rotation: int = 0) -> list[dict]:
    """Every spike-glyph fit on a minimap crop, accepted or candidate.

    Each: `cx`, `cy` (the triangle's centroid, crop px), `state` ("dropped"
    base down, "carried" base up), `side` (scale-1.0 px), `ncc`, `ncc_flip`
    (the other orientation's correlation at the same point), `amp`, `rg`
    (the mean R - G of its keyed pixels), `reason` (None where accepted). `support` (the opaque slab) refuses a
    fit that does not touch it, as `off_slab`. `rotation` is the widget's
    placement (0 or 180): the state names the glyph as drawn on the screen,
    whichever way the baked frame turns it. Sorted strongest first."""
    from .minimap import widget_scale

    sc = widget_scale(crop.shape[1])
    y = spike_yellowness(crop)
    seeds = (y >= SEED_Y).astype(np.uint8)
    if not seeds.any():
        return []
    reach = int(np.ceil(max(SIDES["dropped"]) * sc)) + 4
    n, _lab, st, _cen = cv2.connectedComponentsWithStats(seeds, 8)
    boxes = []
    for i in range(1, n):
        x, yy, w, h = st[i, :4]
        boxes.append([max(0, x - reach), max(0, yy - reach),
                      min(crop.shape[1], x + w + reach), min(crop.shape[0], yy + h + reach)])
    boxes = _merge_windows(boxes)
    found = []
    ys = cv2.GaussianBlur(y, (0, 0), 0.7)
    for x0, y0, x1, y1 in boxes:
        maps = _fit(ys[y0:y1, x0:x1], sc, rotation)
        if maps.get("dropped") is None or maps.get("carried") is None:
            continue
        nd, ad, sd = maps["dropped"]
        nc, ac, scar = maps["carried"]
        best = np.maximum(nd, nc)
        amp = np.where(nd >= nc, ad, ac)
        keep = (best >= NCC_CANDIDATE) & (amp >= AMP_CANDIDATE)
        peak = keep & (best == cv2.dilate(best, np.ones((5, 5), np.uint8)))
        for py, px in zip(*np.nonzero(peak)):
            down = bool(nd[py, px] >= nc[py, px])
            found.append({"cx": int(px + x0), "cy": int(py + y0),
                          "state": "dropped" if down else "carried",
                          "side": float(sd[py, px] if down else scar[py, px]),
                          "ncc": round(float(best[py, px]), 3),
                          "ncc_flip": round(float(nc[py, px] if down else nd[py, px]), 3),
                          "amp": round(float(amp[py, px]), 1)})
    for f in found:
        r = int(np.ceil(f["side"] * sc / 2))
        win = crop[max(0, f["cy"] - r):f["cy"] + r + 1,
                   max(0, f["cx"] - r):f["cx"] + r + 1].astype(np.int16)
        key = y[max(0, f["cy"] - r):f["cy"] + r + 1, max(0, f["cx"] - r):f["cx"] + r + 1] >= SEED_Y
        f["rg"] = round(float((win[..., 2] - win[..., 1])[key].mean()), 1) if key.any() else None
        f["reason"] = glyph_gate(f["ncc"], f["amp"])
        if f["reason"] is None and (f["rg"] is None or f["rg"] > RG_MAX):
            f["reason"] = "orange"
    if support is not None:
        # A glyph must touch the slab, as an icon must (`minimap.icons`); its
        # centre may overhang the floor's edge.
        for f in found:
            r = int(np.ceil(f["side"] * sc / 2))
            if f["reason"] is None and not support[max(0, f["cy"] - r):f["cy"] + r + 1,
                                                   max(0, f["cx"] - r):f["cx"] + r + 1].any():
                f["reason"] = "off_slab"
    # Accepted fits first, then by correlation; one glyph per NMS_PX.
    found.sort(key=lambda f: (f["reason"] is not None, -f["ncc"]))
    out: list[dict] = []
    for f in found:
        if any(np.hypot(f["cx"] - o["cx"], f["cy"] - o["cy"]) < NMS_PX * sc for o in out):
            continue
        out.append(f)
    return out


def _merge_windows(boxes: list[list[int]]) -> list[list[int]]:
    """Union overlapping search windows, so no peak is found twice."""
    boxes = sorted(boxes)
    changed = True
    while changed:
        changed, out = False, []
        for b in boxes:
            for o in out:
                if b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3]:
                    o[:] = [min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])]
                    changed = True
                    break
            else:
                out.append(list(b))
        boxes = out
    return boxes


def accepted(fits: list[dict]) -> list[dict]:
    """The fits `glyph_fits` accepted."""
    return [f for f in fits if f.get("reason") is None]


def _carrier_point(glyph: dict, sc: float, rotation: int = 0) -> tuple[float, float]:
    """Where the carrier's icon centre sits in the baked frame: up and to the
    right of its glyph on the screen, down and to the left where the widget is
    drawn turned over."""
    k = -1.0 if int(rotation) % 360 == 180 else 1.0
    return glyph["cx"] + k * CARRIER_DX * sc, glyph["cy"] + k * CARRIER_DY * sc


def on_glyph(cx: float, cy: float, glyphs: list[dict], sc: float,
             icons=(), rotation: int = 0) -> dict | None:
    """The accepted glyph an icon fit centred at (cx, cy) lands on, or None.

    A carried spike draws over the lower left of its carrier's icon
    [domain:minimap/spike-carrier-overlay], so a fit near a carried glyph may
    be the carrier, and only a fit on the glyph ITSELF is refused:

    * a dropped glyph has no carrier: a fit within ON_GLYPH_PX lands on it;
    * a carried glyph: a fit within CORE_PX of its centroid rings the glyph;
      farther out, up to ON_GLYPH_PX, it is refused only where another icon
      of `icons` (the frame's other fits, dicts with `cx`, `cy`) sits at the
      carrier's place, (CARRIER_DX, CARRIER_DY) from the glyph within
      CARRIER_TOL_PX, and is not this fit (farther than SAME_ICON_PX). The
      glyph then belongs to that icon, and this fit rings the glyph. With no
      carrier seen, the fit may be the carrier pulled toward its own glyph,
      and it is kept.

    `rotation` is the widget's placement: turned over, the carrier's place
    turns with it (`_carrier_point`).

    On 5822b6646448 the self fits within 7.5 px of a glyph an ally carried
    ringed the glyph by eye (18 of 18)."""
    for g in glyphs:
        if g.get("reason") is not None:
            continue
        d = float(np.hypot(cx - g["cx"], cy - g["cy"]))
        if d > ON_GLYPH_PX * sc:
            continue
        if g["state"] == "dropped" or d <= CORE_PX * sc:
            return g
        kx, ky = _carrier_point(g, sc, rotation)
        if np.hypot(cx - kx, cy - ky) <= CARRIER_TOL_PX * sc:
            continue                                   # this fit is the carrier
        if any(np.hypot(i["cx"] - kx, i["cy"] - ky) <= CARRIER_TOL_PX * sc
               and np.hypot(i["cx"] - cx, i["cy"] - cy) > SAME_ICON_PX * sc for i in icons):
            return g
    return None


def carrier_offset(glyph: dict, icons: list[dict], sc: float,
                   rotation: int = 0) -> dict | None:
    """The icon a carried glyph sits under: the nearest icon centre to the
    glyph's centroid plus (CARRIER_DX, CARRIER_DY) on the screen, within
    CARRIER_TOL_PX (`_carrier_point`, turned with `rotation`). `icons` are
    dicts with `cx`, `cy` and any tags; returns the icon with its offset from
    the glyph (baked-frame px over `sc`) added, or None."""
    want = _carrier_point(glyph, sc, rotation)
    best, bd = None, CARRIER_TOL_PX * sc
    for ic in icons:
        d = float(np.hypot(ic["cx"] - want[0], ic["cy"] - want[1]))
        if d <= bd:
            best, bd = ic, d
    if best is None:
        return None
    return {**best, "dx": round((best["cx"] - glyph["cx"]) / sc, 2),
            "dy": round((best["cy"] - glyph["cy"]) / sc, 2)}


@lru_cache(maxsize=1)
def marker_template() -> np.ndarray:
    return np.load(TEMPLATE_FILE)["marker"].astype(np.float32)


def roster_marker(crop: np.ndarray) -> dict:
    """The spike marker on an ally roster crop: `slot` (0-4, left to right,
    the bar's packed position) or None, `ncc` (the best slot's match),
    `slot_ncc` (each slot's match at its own column, +/-1 px), `off_ncc` (the
    best match anywhere on the band) and `reason` (None where a slot is read,
    else `no_marker` or `roster_size`)."""
    if crop is None or crop.shape[0] != ROSTER_H:
        return {"slot": None, "ncc": None, "reason": "roster_size"}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = cv2.matchTemplate(g[MARK_ROWS[0]:MARK_ROWS[1]], marker_template(),
                          cv2.TM_CCOEFF_NORMED)
    per = []
    for k in range(5):
        x = MARK_X0 + k * MARK_PITCH
        win = m[:, max(0, x - 1):x + 2]
        per.append(round(float(win.max()), 3) if win.size else -1.0)
    k = int(np.argmax(per))
    out = {"slot": None, "ncc": per[k], "slot_ncc": per, "off_ncc": round(float(m.max()), 3),
           "reason": "no_marker"}
    if per[k] >= MARK_NCC_MIN:
        out.update(slot=k, reason=None)
    return out


#: The grid step, in seconds, over the minimap cache's frames.
STEP_S = 1.0
#: How far, in ms, a roster crop may lie from the minimap frame it pairs with.
ROSTER_GAP_MS = 250.0


def read_frame(crop: np.ndarray, ctx: dict) -> dict:
    """One minimap frame's spike reading.

    `ctx` holds the baked geometry's `floor`, `slab`, `static` and `sgray`,
    and `rotation`, the widget placement's (0 where absent). Returns
    `rotation`, `glyphs` (every fit, accepted or candidate) and, where a carried
    glyph was accepted, `icons`: the self fit and ally fits (`minimap`
    owns them) as `channel`, `cx`, `cy`, `r`, which the carrier check pairs
    with the glyph. Or a refusal `reason`."""
    from .minimap import ally_icons, self_icons, widget_drawn

    if crop.shape[:2] != ctx["floor"].shape:
        return {"reason": "crop_size"}
    if not widget_drawn(crop, ctx["sgray"], ctx["floor"]):
        return {"reason": "widget_not_drawn"}
    rotation = int(ctx.get("rotation") or 0)
    fits = glyph_fits(crop, ctx["slab"], rotation)
    row = {"rotation": rotation, "glyphs": fits, "reason": None}
    if any(g["reason"] is None and g["state"] == "carried" for g in fits):
        me = self_icons(crop, ctx["floor"], require_facing=False, support=ctx["slab"])[:1]
        al = ally_icons(crop, ctx["floor"], support=ctx["slab"], static=ctx["static"])
        row["icons"] = ([{"channel": "self", "cx": round(f["cx"], 2), "cy": round(f["cy"], 2),
                          "r": round(float(f["r"]), 2)} for f in me]
                        + [{"channel": "ally", "cx": round(f["cx"], 2), "cy": round(f["cy"], 2),
                            "r": round(float(f["r"]), 2)} for f in al])
    return row


__all__ = ["SPIKE_VERSION", "glyph_fits", "accepted", "on_glyph", "carrier_offset",
           "roster_marker", "spike_yellowness", "glyph_template", "glyph_gate", "read_frame",
           "STEP_S", "ROSTER_GAP_MS"]
