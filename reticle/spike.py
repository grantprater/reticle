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
[domain:minimap/spike-inversion]. The template is the game's own texture,
`Minimap_BombIcon` of build release-13.06-shipping-18-5590001 (`provenance`
names it and its sha256; a changed file refuses), drawn in the game's box:
24 units dropped (`AresMinimapBombWidget`), 18 carried and turned 180
(`CharacterPortraitMinimapWidget.BombIcon`) [domain:minimap/spike-glyph-texture],
times the measured
`BOX_FRACTIONS`, times the capture's map scale (`drawn_boxes`). It is warped
linearly onto an 8x canvas and shrunk with `INTER_AREA`, never thresholded.
The fit is a normalised cross-correlation of that template against the
crop's yellowness, min(R, G) - B, plus the fitted amplitude: the yellowness
step the template explains, and the peak refines to a sub-pixel centre.
The correlation alone admits noise, since it ignores
scale, and the pale self ring correlates at 0.6-0.75; the amplitude separates
them because the glyph is a saturated yellow and the ring is not. Yellowness
is chroma, so under 4:2:0 [domain:capture/chroma-420] it arrives in 2x2
blocks and the dots are not resolved; the silhouette and the dark circle are.
A fit whose correlation or amplitude falls short of the gate is kept as a
`candidate` with its reason, never dropped.

Measured before the gate was set (2026-09-28, 250 labelled fits on
c40d950031bb and 5822b6646448, the fits every 0.6+ correlation peak, on the
hand-drawn triangle of spike-0.2.0; spike-0.3.0 keeps the gates):
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
The game places the carried glyph (-7, +7) units from its portrait's centre
(`BombIcon`'s translation), which the measured `CARRIER_DX`, `CARRIER_DY`
agree with.

**The roster marker, fitted as a template.** The ally roster marks the
carrier [domain:hud/spike-carrier-marker]: a white badge holding the glyph,
below the carrier's health pill. The `hud_roster` ROI clips it after its top
ten rows, which carry the badge's rim and the glyph's upper half; the stored
template (`templates/valorant-16x9-spike-marker.npz`) is the mean of 30 such
crops. The game draws the marker from `TX_Icon_Bomb_v2`
[domain:hud/spike-carrier-marker-texture]; that texture drawn at 42 px
correlates 0.87 with the mean but scores washed-out frames lower, so the
marker stays mined (`TEMPLATE_FILE` says what it lost). Its left edge sits at column 11 + 66 k of the 1080p crop for slot k,
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

#: The game's draw boxes, in widget units: `AresMinimapBombWidget` draws
#: `Minimap_BombIcon` dropped in a 24 x 24 box (its `Minimap Size`), and
#: `CharacterPortraitMinimapWidget.BombIcon` draws it carried, 18 x 18 and
#: turned 180 (its RenderTransform Angle). A unit is a base px at
#: `geometry.SCALE_REF_KEY`, times `geometry.MapScale.scale` (the widget
#: scale times the map zoom) on another key.
GAME_BOX = {"dropped": 24.0, "carried": 18.0}
#: The box fractions fitted. The capture draws the glyph smaller than its box
#: times the scale, as it draws the self icon's 24-unit rim at 22 px
#: [domain:minimap/icons-follow-map-zoom]. Over 40 accepted spike-0.2.0 glyphs
#: per state and session, the best fraction's median was 0.90 dropped and
#: 0.90 carried on a06f04a0059f (465 px), 0.95 and 0.775 on 3694746e4e54 and
#: 0.825 and 0.775 on bfad2778a372 (331 px). The carried glyph on the 331 px
#: widget departs from the one transform; it is a measured exception, so the
#: fit searches this band rather than keeping a per-size table.
BOX_FRACTIONS = (0.775, 0.85, 0.925)
#: Scale-1.0 boxes fitted per state, stored with the parameters.
SIDES = {k: tuple(round(v * f, 3) for f in BOX_FRACTIONS) for k, v in GAME_BOX.items()}
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

#: The game export the glyph and the marker are drawn from, in the store's
#: game-file reference, as (set, path in the set). Each set's
#: `manifest.jsonl` lists the texture's sha256, which every load checks.
GAME_BUILD = "release-13.06-shipping-18-5590001"
GLYPH_TEXTURE = ("minimap",
                 "ShooterGame/Content/UI/InGame/Minimap/Textures/BombTextures/Minimap_BombIcon.png")
#: The roster marker's template: the mean of 30 mined `hud_roster` crops.
#: The game draws the marker from `TX_Icon_Bomb_v2` turned 180 in a 42-unit
#: box [domain:hud/spike-carrier-marker-texture], but that texture drawn at
#: 42 px (row phases -1/3 to 1, column phases -1 to 0, boxes 41-43) scored
#: the washed-out frames lower than this mean: on nine matches 12 frames the
#: mean marks at 0.65-0.76 fell to 0.53-0.65, and one lost frame on
#: c40d950031bb (793.0 s) bound a carrier loss to a teammate's death Riot
#: gives to another player. The mean keeps the capture's compositing that
#: the texture lacks, so the marker stays mined (game-spike-20261003).
TEMPLATE_FILE = Path(__file__).parent / "templates" / "valorant-16x9-spike-marker.npz"
#: A texture is drawn at a fractional box on a canvas this many times finer,
#: warped linearly, then shrunk with INTER_AREA.
SUPERSAMPLE = 8


def game_dir(store_root=None) -> Path:
    """The build's export in `store_root` (default: the default store)."""
    if store_root is None:
        from .store import DEFAULT_STORE
        store_root = DEFAULT_STORE
    return Path(store_root) / "reference" / "game-files" / GAME_BUILD


@lru_cache(maxsize=8)
def _texture(which: tuple[str, str], store_root=None) -> tuple[np.ndarray, str]:
    """A game texture as float BGRA 0..1 and its sha256, checked against its
    set's manifest. Raises FileNotFoundError when the export, its manifest or
    the texture is missing, and ValueError when the bytes differ from the
    manifest's sha256: a reader without its reference is a fault, not a read."""
    import hashlib
    import json
    d = game_dir(store_root) / which[0]
    man, p = d / "manifest.jsonl", d / which[1]
    if not man.is_file() or not p.is_file():
        raise FileNotFoundError(f"spike: no game texture {p} with {man}")
    want = None
    for line in man.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if str(r.get("output", "")).replace("\\", "/").endswith(which[1]):
                want = r.get("sha256")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if want != digest:
        raise ValueError(f"spike: {which[1]} sha256 {digest} is not the manifest's {want}")
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        raise ValueError(f"spike: {which[1]} has no alpha")
    return im.astype(np.float32) / 255.0, digest


def provenance(store_root=None) -> dict:
    """The build and the glyph texture's set, path and sha256, and the mined
    marker template's file and sha256, for a stored head."""
    import hashlib
    return {"build": GAME_BUILD,
            "textures": {"glyph": {"set": GLYPH_TEXTURE[0], "path": GLYPH_TEXTURE[1],
                                   "sha256": _texture(GLYPH_TEXTURE, store_root)[1]}},
            "marker_template": {"file": TEMPLATE_FILE.name,
                                "sha256": hashlib.sha256(TEMPLATE_FILE.read_bytes()).hexdigest()},
            "filters": f"premultiplied texture warped linearly onto a canvas {SUPERSAMPLE}x "
                       "finer, then INTER_AREA to the drawn size"}


def _draw(plane: np.ndarray, box_w: float, box_h: float, n_w: int, n_h: int,
          dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    """`plane` (one premultiplied texture channel) drawn in a box_w x box_h px
    box centred on an n_w x n_h canvas (an odd side centres it on a pixel),
    moved by (dx, dy) px: warped linearly onto a canvas SUPERSAMPLE times
    finer, then shrunk with INTER_AREA."""
    ss = SUPERSAMPLE
    sx, sy = box_w * ss / plane.shape[1], box_h * ss / plane.shape[0]
    cx, cy = (n_w * ss - 1) / 2.0 + dx * ss, (n_h * ss - 1) / 2.0 + dy * ss
    m = np.float32([[sx, 0, 0.5 * sx + cx - box_w * ss / 2],
                    [0, sy, 0.5 * sy + cy - box_h * ss / 2]])
    big = cv2.warpAffine(np.ascontiguousarray(plane), m, (n_w * ss, n_h * ss),
                         flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return cv2.resize(big, (n_w, n_h), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=1)
def _glyph_yellowness() -> tuple[np.ndarray, float]:
    """The glyph texture's yellowness, min(R, G) - B of its premultiplied
    colour (the same over any grey floor), and its fill level, the median
    over pixels above half: a template's 1 is the glyph's full yellow."""
    t, _ = _texture(GLYPH_TEXTURE)
    pm = t[..., :3] * t[..., 3:4]
    y = np.clip(np.minimum(pm[..., 2], pm[..., 1]) - pm[..., 0], 0, None)
    return y, float(np.median(y[y > 0.5]))


def spike_yellowness(crop: np.ndarray) -> np.ndarray:
    """min(R, G) - B, clipped at 0: the spike's saturated yellow is high,
    grey floor and teal are near 0."""
    b, g, r = cv2.split(crop)
    # uint8 arithmetic saturates at 0, which is the clip
    return cv2.subtract(cv2.min(r, g), b).astype(np.float32)


@lru_cache(maxsize=64)
def glyph_template(box: float, base_down: bool, margin: int = 3) -> np.ndarray:
    """The glyph's yellowness model: the game's `Minimap_BombIcon` drawn in a
    `box` px square (`_draw`), base down as the texture stands or turned 180,
    in fill units (1 is the glyph's full yellow, 0 its black circle, outline
    and the teal glow around it). The centre pixel is the box's centre;
    `template_centroid` places the triangle's centroid from it."""
    y, fill = _glyph_yellowness()
    if not base_down:
        y = y[::-1, ::-1]
    n = 2 * (int(np.ceil(box / 2)) + margin) + 1
    return _draw(y, box, box, n, n) / fill


@lru_cache(maxsize=64)
def template_centroid(box: float, base_down: bool) -> tuple[float, float]:
    """The yellowness-weighted centroid of `glyph_template` less its centre
    pixel, px: the triangle's centroid from the box's centre, which a fit
    reports as the glyph's position, as spike-0.2.0's drawn triangle did."""
    t = glyph_template(box, base_down)
    yy, xx = np.mgrid[:t.shape[0], :t.shape[1]]
    c, w = t.shape[0] // 2, float(t.sum())
    return float((t * xx).sum() / w - c), float((t * yy).sum() / w - c)


def _base_down(state: str, rotation: int = 0) -> bool:
    """Whether a glyph in `state` points its base down in the baked frame: on
    the screen a dropped glyph is base down, and a widget drawn turned over
    (`rotation` 180) arrives turned back, the glyph with it."""
    return (state == "dropped") != (int(rotation) % 360 == 180)


def drawn_boxes(width_px: float, scale: float | None = None) -> dict[str, list[float]]:
    """Per state, the drawn boxes (crop px) the fit tries: GAME_BOX times
    each of BOX_FRACTIONS times `scale` (`MapScale.scale`; None, the
    widget's scale, `minimap.drawn_scale`). Every reader in `reticle/` names
    its scale since spike-0.4.0, so the zoom band that served callers
    without one (ZOOM_RANGE) is retired."""
    from .minimap import drawn_scale
    fr = [f * drawn_scale(width_px, scale) for f in BOX_FRACTIONS]
    return {k: [round(v * f, 2) for f in fr] for k, v in GAME_BOX.items()}


def _fit(y: np.ndarray, boxes: dict[str, list[float]], rotation: int = 0):
    """Per state, the best correlation, its amplitude and drawn box at every
    pixel of `y` (-1 where the window does not fit).

    The window's standard deviation under each template comes from one pair
    of integral images (float64) shared by every template, not from two
    correlations with a flat kernel per template."""
    s1, s2 = cv2.integral2(np.ascontiguousarray(y, np.float32), sdepth=cv2.CV_64F,
                           sqdepth=cv2.CV_64F)
    out = {}
    for state, sides in boxes.items():
        best = None
        for s in sides:
            t = glyph_template(s, _base_down(state, rotation))
            if t.shape[0] > y.shape[0] or t.shape[1] > y.shape[1]:
                continue
            ncc = cv2.matchTemplate(y, t, cv2.TM_CCOEFF_NORMED)
            sd = _window_sd(s1, s2, *t.shape)
            amp = ncc * sd / _template_std(s, _base_down(state, rotation))
            # each map at its window's centre pixel: -1 and 0 where none fits
            p, (hh, ww) = t.shape[0] // 2, ncc.shape
            ncc_full = np.full(y.shape, -1, ncc.dtype)
            amp_full = np.zeros(y.shape, amp.dtype)
            ncc_full[p:p + hh, p:p + ww] = ncc
            amp_full[p:p + hh, p:p + ww] = amp
            ncc, amp = ncc_full, amp_full
            if best is None:
                best = [ncc, amp, np.full(y.shape, s, np.float32)]
            else:
                w = ncc > best[0]
                best = [np.where(w, ncc, best[0]), np.where(w, amp, best[1]),
                        np.where(w, s, best[2])]
        out[state] = best
    return out


@lru_cache(maxsize=64)
def _template_std(box: float, base_down: bool) -> float:
    """`glyph_template`'s standard deviation, as `_fit` divides by it."""
    return float(glyph_template(box, base_down).std())


def _window_sd(s1: np.ndarray, s2: np.ndarray, th: int, tw: int) -> np.ndarray:
    """The standard deviation over every `th` x `tw` window that fits, from
    `cv2.integral2`'s sum and squared sum: `matchTemplate`'s valid layout,
    as float32."""
    def box(s):
        return s[th:, tw:] - s[:-th, tw:] - s[th:, :-tw] + s[:-th, :-tw]
    n = float(th * tw)
    mu = box(s1) / n
    return np.sqrt(np.maximum(box(s2) / n - mu * mu, 0)).astype(np.float32)


def glyph_gate(ncc: float, amp: float) -> str | None:
    """None where a glyph fit is accepted, else why not."""
    if (ncc >= NCC_MIN and amp >= AMP_MIN) or (ncc >= NCC_STRONG and amp >= AMP_PARTIAL):
        return None
    return "weak_correlation" if ncc < NCC_MIN else "weak_amplitude"


def glyph_fits(crop: np.ndarray, support: np.ndarray | None = None,
               rotation: int = 0, scale: float | None = None) -> list[dict]:
    """Every spike-glyph fit on a minimap crop, accepted or candidate.

    Each: `cx`, `cy` (the triangle's centroid, crop px, fitted to a tenth of
    a pixel), `state` ("dropped" base down, "carried" base up), `side` (the
    drawn box over the scale: scale-1.0 px), `ncc`, `ncc_flip` (the other
    orientation's correlation at the same point), `amp`, `rg` (the mean
    R - G of its keyed pixels), `reason` (None where accepted). `support`
    (the opaque slab) refuses a fit that does not touch it, as `off_slab`.
    `rotation` is the widget's placement (0 or 180): the state names the
    glyph as drawn on the screen, whichever way the baked frame turns it.
    `scale` is the key's `MapScale.scale`; None, the widget's scale
    (`drawn_boxes`). Sorted strongest first."""
    from .minimap import drawn_scale

    unit = drawn_scale(crop.shape[1], scale)
    y = spike_yellowness(crop)
    seeds = (y >= SEED_Y).astype(np.uint8)
    if not seeds.any():
        return []
    drawn = drawn_boxes(crop.shape[1], scale)
    reach = int(np.ceil(max(drawn["dropped"]))) + 4
    # The seeds' components, labelled inside the seeds' bounding box only.
    bx, by, _bw, _bh = cv2.boundingRect(seeds)
    n, _lab, st, _cen = cv2.connectedComponentsWithStats(seeds[by:by + _bh, bx:bx + _bw], 8)
    boxes = []
    for i in range(1, n):
        x, yy, w, h = st[i, :4]
        x, yy = x + bx, yy + by
        boxes.append([max(0, x - reach), max(0, yy - reach),
                      min(crop.shape[1], x + w + reach), min(crop.shape[0], yy + h + reach)])
    boxes = _merge_windows(boxes)
    found = []
    ys = cv2.GaussianBlur(y, (0, 0), 0.7)
    for x0, y0, x1, y1 in boxes:
        maps = _fit(ys[y0:y1, x0:x1], drawn, rotation)
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
            state = "dropped" if down else "carried"
            box = float(sd[py, px] if down else scar[py, px])
            ox, oy = template_centroid(box, _base_down(state, rotation))
            fx, fy = _subpixel(best, py, px)
            found.append({"cx": round(float(px + x0 + fx + ox), 2),
                          "cy": round(float(py + y0 + fy + oy), 2),
                          "px": int(px + x0), "py": int(py + y0), "state": state,
                          "side": round(box / unit, 3),
                          "ncc": round(float(best[py, px]), 3),
                          "ncc_flip": round(float(nc[py, px] if down else nd[py, px]), 3),
                          "amp": round(float(amp[py, px]), 1)})
    for f in found:
        r = int(np.ceil(f["side"] * unit / 2))
        cx, cy = f.pop("px"), f.pop("py")
        win = crop[max(0, cy - r):cy + r + 1, max(0, cx - r):cx + r + 1].astype(np.int16)
        key = y[max(0, cy - r):cy + r + 1, max(0, cx - r):cx + r + 1] >= SEED_Y
        f["rg"] = round(float((win[..., 2] - win[..., 1])[key].mean()), 1) if key.any() else None
        f["reason"] = glyph_gate(f["ncc"], f["amp"])
        if f["reason"] is None and (f["rg"] is None or f["rg"] > RG_MAX):
            f["reason"] = "orange"
    if support is not None:
        # A glyph must touch the slab, as an icon must (`minimap.icons`); its
        # centre may overhang the floor's edge.
        for f in found:
            r = int(np.ceil(f["side"] * unit / 2))
            cx, cy = int(round(f["cx"])), int(round(f["cy"]))
            if f["reason"] is None and not support[max(0, cy - r):cy + r + 1,
                                                   max(0, cx - r):cx + r + 1].any():
                f["reason"] = "off_slab"
    # Accepted fits first, then by correlation; one glyph per NMS_PX.
    found.sort(key=lambda f: (f["reason"] is not None, -f["ncc"]))
    out: list[dict] = []
    for f in found:
        if any(np.hypot(f["cx"] - o["cx"], f["cy"] - o["cy"]) < NMS_PX * unit for o in out):
            continue
        out.append(f)
    return out


def _subpixel(m: np.ndarray, py: int, px: int) -> tuple[float, float]:
    """The peak's offset from (px, py) by a parabola through each axis's
    three correlations, held within half a pixel; 0 at an edge."""
    def axis(a, b, c):
        d = a - 2 * b + c
        return 0.0 if d >= 0 or min(a, c) < -0.5 else float(np.clip(0.5 * (a - c) / d, -0.5, 0.5))
    h, w = m.shape
    fx = axis(m[py, px - 1], m[py, px], m[py, px + 1]) if 0 < px < w - 1 else 0.0
    fy = axis(m[py - 1, px], m[py, px], m[py + 1, px]) if 0 < py < h - 1 else 0.0
    return fx, fy


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
    """The roster marker's grey template, 0..255 (`TEMPLATE_FILE`)."""
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
    band = g[MARK_ROWS[0]:MARK_ROWS[1]]
    m = cv2.matchTemplate(band, marker_template(), cv2.TM_CCOEFF_NORMED)
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
    `rotation`, the widget placement's (0 where absent), and `scale`, the
    key's `geometry.MapScale.scale` (`geometry.drawn_scale`), which the
    glyph boxes and the self and ally ring fits take. Returns
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
    fits = glyph_fits(crop, ctx["slab"], rotation, ctx.get("scale"))
    row = {"rotation": rotation, "glyphs": fits, "reason": None}
    if any(g["reason"] is None and g["state"] == "carried" for g in fits):
        sc = ctx.get("scale")
        me = self_icons(crop, ctx["floor"], require_facing=False, support=ctx["slab"],
                        scale=sc)[:1]
        al = ally_icons(crop, ctx["floor"], support=ctx["slab"], static=ctx["static"],
                        scale=sc)
        row["icons"] = ([{"channel": "self", "cx": round(f["cx"], 2), "cy": round(f["cy"], 2),
                          "r": int(f["r"])} for f in me]
                        + [{"channel": "ally", "cx": round(f["cx"], 2), "cy": round(f["cy"], 2),
                            "r": int(f["r"])} for f in al])
    return row


__all__ = ["SPIKE_VERSION", "glyph_fits", "accepted", "on_glyph", "carrier_offset",
           "roster_marker", "spike_yellowness", "glyph_template", "glyph_gate", "read_frame",
           "STEP_S", "ROSTER_GAP_MS"]
