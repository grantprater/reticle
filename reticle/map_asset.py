r"""The minimap of one MAP, from the game's own files, and the transform that draws it in a widget.

One asset per map, one transform per capture profile. Every session on a map
reads the same asset; its profile's transform places it in that session's
widget (the player, 2026-10-05: *the same minimap asset, transformed for all
sessions on the same map*). A capture still determines only the widget's
size, placement and orientation [domain:capture/session-pixels-are-not-the-map].

The asset
---------
VALORANT draws a map's minimap from two textures, exported by the store's
extractor (`<store>/tools/game-extract`, CUE4Parse) into
`<store>/reference/game-files/<BUILD>/minimap-geometry/`, whose
`manifest.jsonl` names each one's game path and sha256:

* `TX_Map_<code>_FogOfWar`, the map UNLIT, named as `DisplayIcon` by the
  map's `<code>_UIData` (Ascent's `..._FogOfWar_Update` is byte-identical to
  `..._FogOfWar`); the valorant-api display icon and the wiki art are this
  texture;
* `TX_Map_<code>_Revealed`, the same plan LIT where an ally can see.

`classes` quantises the fog texture into terrain classes (VOID, FLOOR, RAMP,
SHADOW, LINE, SITE) with a level ladder, at texture resolution: map-space
fields, the same for every profile. `ROTATION` is the map's turn in the game's
fixed orientation, read off by the player except where marked.

The transform
-------------
A profile names a capture's minimap settings (`reticle/profiles.py`). The game
has two: the widget's size and the map's scaling inside it
[domain:capture/minimap-size-settings]. So a profile carries two placements,
fitted on the training keys only (`prototypes/minimap_geometry.py fit`) and
frozen in `reticle/frozen/geometry_profiles.json`:

* the MAP's: a scale (widget px per texture px) and the widget point the
  texture's centre lands on. A free fit on each of the eleven captured keys put
  that point within [metric:official_geometry/all#centre_dev_max_px=0.127] px
  of the fitted one and the scale within
  [metric:official_geometry/all#scale_dev_max_pct=0.139]%;
* the WIDGET's: the drawn ring [domain:minimap/widget-ring], centred on the
  same point, whose radius follows the widget size (162.7 against 229.75 px,
  the widget widths' ratio) rather than the map scaling. At the largest map
  scaling the map is painted only inside it
  [domain:capture/largest-scaling-shows-whole-map-belief], so it also clips.

What differs by profile beyond the transform is what a capture adds, and each
is a fitted per-profile constant: the gain of the opaque map (the smaller
widget renders the line-work dimmer), the void's colour and darkening (live
world through the transparent widget [domain:minimap/transparency], a
background for differencing, never map), and the per-pixel noise `sd_lo` and
`sd_hi`. The line-work's weight is not a field: it falls out of drawing the
texture through `RT_SIDE` at the profile's scale. The occluder and line arrays
are read in widget pixels from the drawn static and from the player's answers
on two bigmap keys, so they stay per key (`reticle/occluders.py`).

The world
---------
`world_to_texture` carries game units to texture px through the constants the
map's `<code>_UIData` stores (`XMultiplier`, `XScalarToAdd` and their Y twins;
valorant-api publishes the same numbers), then adds the map's `world_offset`.
That offset, one to two texture px, lies between the constants and the drawn
texture: alike at both profiles and in every match of a map. It is fitted on
development matches' Riot kill positions (`prototypes/minimap_geometry.py
--fit-world`) and frozen in `reticle/frozen/world_offsets.json`; a map no
development match covers keeps zero. Scored leave-one-match-out, it cut the
mean victim-position error by
[metric:official_geometry/world_lomo/valorant-16x9#change_vs_official=-0.066]
px on the 331 px widget and by
[metric:official_geometry/world_lomo/valorant-16x9-bigmap#change_vs_official=-0.375]
px on the 465 px one. `shade_fit` places the world, so it carries the offset.

The widget draws each bomb site's letter where the map's gameplay level places
a `MinimapSite{A,B,C}` actor (its `TheScene` location), exported into
`<store>/reference/game-files/<BUILD>/minimap-sites/` with the letter widgets
and the `<X>Site_Letter` textures. Each widget names an upright 24-unit
glyph, black at half opacity. `render` darkens the static and the noise
bounds under the letters (`letter_cover`). The letters' side
(`LETTER_TEX_PX`) is the one fitted number: the files do not state the unit
the widget's size is in.

`render` draws a `(map, profile)` key's fields; `reticle/geometry.py` caches
them per key and rebuilds a cache whose `built_by` is not `asset_stamp`.

Owns [owns:map-asset].
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .store import DEFAULT_STORE

#: The game build whose textures are drawn.
BUILD = "release-13.06-shipping-18-5590001"
#: The training keys every per-profile constant was fitted on.
TRAIN_KEYS = ("ascent__valorant-16x9", "ascent__valorant-16x9-bigmap",
              "lotus__valorant-16x9", "lotus__valorant-16x9-bigmap")
PROFILES_FILE = Path(__file__).resolve().parent / "frozen" / "geometry_profiles.json"
#: Each map's world offset, texture px (`world_offset`).
WORLD_FILE = Path(__file__).resolve().parent / "frozen" / "world_offsets.json"
#: The site letters' side in texture px: fitted on the training keys' ten
#: letters (sd 1.0) and held by the sixteen others. It is twice the letter
#: widget's `Minimap Size` (24) within 1.3%, which no file states as a rule.
LETTER_TEX_PX = 47.4
#: The letter widget's `ColorAndOpacity` alpha (`AresMinimapSite*Widget`).
LETTER_OPACITY = 0.5
#: The texture is resampled bilinearly to this side, then bilinearly into the
#: widget. Of seven filters tried it reproduced the capture's line-work best on
#: the training keys.
RT_SIDE = 768

#: The map's turn in the game's fixed orientation. READ OFF BY THE PLAYER,
#: 2026-09-05, not fitted; `prototypes/wiki_map.py fit` recovers 270 for
#: Ascent and 0 for Lotus unprompted, which makes the table checkable. Two
#: values only: a long map is turned to fit the square widget. Summit is
#: MEASURED: the 0-360 search placed it at 0 on `summit__valorant-16x9`, and the
#: texture's free fit agrees (2026-10-05).
ROTATION = {
    "bind": 0.0, "breeze": 0.0, "fracture": 0.0, "pearl": 0.0,
    "lotus": 0.0, "sunset": 0.0, "summit": 0.0,
    "haven": 270.0, "split": 270.0, "ascent": 270.0,
    "icebox": 270.0, "abyss": 270.0, "corrode": 270.0,
}

#: Pixel classes `sd_lo`/`sd_hi` and the void offsets are tabled by.
C_FLAT, C_STRUCT, C_EDGE, C_VOID = 0, 1, 2, 3

# ---------------------------------------------------------------- art classes
# The six classes the art draws, and the argument for each constant, were
# measured on the wiki art (this texture) by `prototypes/map_shade.py`, now
# retired; its evidence is `docs/archive/MAP_SHADE-through-2026-10-05.md`.
VOID, FLOOR, RAMP, SHADOW, LINE, SITE = 0, 1, 2, 3, 4, 5
KIND_NAME = {VOID: "VOID", FLOOR: "FLOOR", RAMP: "RAMP",
             SHADOW: "SHADOW", LINE: "LINE", SITE: "SITE"}
#: Alpha above which a texel is map. The channel is near-binary.
ALPHA_MIN = 40
#: Above this HSV saturation a texel is a bomb site, not terrain. The olive is
#: the only non-grey the art draws, 4-8% of the opaque texels on every map, so
#: this separates two populations with nothing between them.
SAT_MAX = 30
#: At or above this grey a texel is line-work, not terrain. Highest terrain
#: rung to lowest line rung: ascent 145->221, split 143->221, sunset 146->221,
#: lotus 186->221, haven 145->230, abyss 186->196.
LINE_MIN = 190
#: A grey must hold this share of its family's INTERIOR to be a rung. Interior,
#: because the antialiasing between two rungs holds 0.24-0.35% at every value
#: between them on Ascent, while a rung is a region whose neighbourhoods are
#: one grey.
MIN_SHARE = 0.002
#: Greys this close are one rung drawn twice (118 and 119 on every map).
MERGE_GAP = 2
#: An off-rung region is terrain when at least this share of the art and this
#: thick (px at 2048 px of art, scaled by side). Both halves are needed:
#: Lotus's 186 wall edging is 1.3% of the grey family at inscribed radius 2,
#: while Ascent's ramps and shadow are single regions 12-22 px thick.
MIN_REGION = 3e-4
MIN_RADIUS = 5.0
#: A thin off-rung region this close to a rung is that rung's antialiasing.
SNAP_MAX = 8
#: Off-rung greys are banded this wide, so a ramp keeps where on the slope it is.
BAND = 4
#: Below this total coverage a widget pixel is off the map; with a near-binary
#: alpha it fires only on the slab's outer edge.
COVER_MIN = 0.5


def game_dir(store=DEFAULT_STORE) -> Path:
    return Path(store) / "reference" / "game-files" / BUILD


def texture_set(store=DEFAULT_STORE) -> Path:
    return game_dir(store) / "minimap-geometry"


@lru_cache(maxsize=4)
def _uidata(store: str) -> dict:
    """Map name (lower case) -> (codename, the fog texture's game path)."""
    out = {}
    root = game_dir(store) / "minimap" / "ShooterGame" / "Content" / "Maps"
    for p in sorted(root.glob("*/*_UIData.json")):
        rows = json.loads(p.read_text(encoding="utf-8"))
        props = next((r.get("Properties") or {} for r in rows
                      if str(r.get("Name", "")).startswith("Default__")), {})
        name = ((props.get("DisplayName") or {}).get("SourceString") or "").strip().lower()
        icon = (props.get("DisplayIcon") or {}).get("ObjectPath")
        if name and icon:
            out[name] = (p.parent.name, icon.split(".")[0])
    return out


def maps(store=DEFAULT_STORE) -> dict:
    return dict(_uidata(str(store)))


@lru_cache(maxsize=4)
def _texture_manifest(store: str) -> tuple:
    p = texture_set(store) / "manifest.jsonl"
    if not p.is_file():
        raise SystemExit(f"no texture set at {p.parent} -- export it with game-extract "
                         f"(see reticle/map_asset.py)")
    return tuple(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip())


def textures(map_name: str, store=DEFAULT_STORE) -> dict:
    """The fog and revealed textures of one map, as their manifest rows."""
    ui = _uidata(str(store))
    if map_name not in ui:
        raise SystemExit(f"{map_name}: no UIData names it")
    code, fog_game = ui[map_name]
    rows = _texture_manifest(str(store))
    want = "ShooterGame/Content/" + fog_game.removeprefix("/Game/") + ".uasset"
    fog = next((r for r in rows if r["game_path"] == want), None)
    if fog is None:
        raise SystemExit(f"{map_name}: {want} is not in the texture set")
    folder = want.rsplit("/", 1)[0]
    rev = sorted((r for r in rows if r["game_path"].rsplit("/", 1)[0] == folder
                  and "_Revealed" in r["game_path"] and r.get("status") == "ok"),
                 key=lambda r: r["game_path"])
    if not rev:
        raise SystemExit(f"{map_name}: no revealed texture beside {want}")
    return {"code": code, "fog": fog, "rev": rev[-1]}


def rotation(map_name: str) -> float:
    if map_name not in ROTATION:
        raise SystemExit(f"{map_name}: no rotation in map_asset.ROTATION -- ask the player")
    return ROTATION[map_name]


def read_bgra(row: dict, store=DEFAULT_STORE) -> np.ndarray:
    im = cv2.imread(str(texture_set(store) / row["output"]), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        raise SystemExit(f"cannot read {row['output']} as BGRA")
    return im


def premultiplied(im: np.ndarray) -> np.ndarray:
    """BGRA uint8 -> premultiplied BGRA float32 in [0, 1]."""
    f = im.astype(np.float32) / 255.0
    a = f[..., 3:4]
    return np.concatenate([f[..., :3] * a, a], axis=2)


# ---------------------------------------------------------------- classes

def _rungs(g, fam, flat, k) -> np.ndarray:
    """The quantised levels of one family, off its INTERIOR. See `MIN_SHARE`."""
    interior = (cv2.erode(fam.astype(np.uint8), k) > 0) & flat
    if interior.sum() < 100:
        interior = fam
    v, c = np.unique(g[interior], return_counts=True)
    keep = c >= MIN_SHARE * c.sum()
    v, c = v[keep], c[keep]
    out: list[int] = []
    for i in np.argsort(-c):
        r = int(v[i])
        if all(abs(r - o) > MERGE_GAP for o in out):
            out.append(r)
    return np.array(sorted(out), np.int16)


def art_classes(im: np.ndarray, name: str = "art"):
    """A BGRA map image, cropped to its alpha bbox, as (kind, shade, step) per
    texel, with the terrain ladder and its base. Quantise first, warp second:
    a warp cannot un-blend two rungs it has averaged."""
    if im is None or im.ndim != 3 or im.shape[2] < 4:
        raise SystemExit(f"{name}: the art has no alpha channel")
    a = im[:, :, 3] > ALPHA_MIN
    ys, xs = np.where(a)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    a = a[sl]
    bgr = im[sl][:, :, :3]
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    site = a & (sat > SAT_MAX)
    grey = a & ~site
    kind = np.zeros(a.shape, np.uint8)
    shade = np.zeros(a.shape, np.uint8)
    step = np.zeros(a.shape, np.int8)
    band = np.clip(g // BAND * BAND + BAND // 2, 1, 255).astype(np.uint8)
    side = max(a.shape)
    kern = np.ones((5, 5) if side > 1024 else (3, 3), np.uint8)
    flat = cv2.dilate(g.astype(np.uint8), kern) == cv2.erode(g.astype(np.uint8), kern)
    ladder = _rungs(g, grey & (g < LINE_MIN), flat, kern)
    if not len(ladder):
        raise SystemExit(f"{name}: no terrain rungs under {LINE_MIN}")
    base = int(ladder[int(np.argmax([(grey & (np.abs(g - r) <= MERGE_GAP)).sum()
                                     for r in ladder]))])
    base_i = int(np.where(ladder == base)[0][0])

    def ordinal(v):
        return (np.abs(np.asarray(v)[..., None] - ladder[None, :]).argmin(-1)
                - base_i).astype(np.int8)

    line = grey & (g >= LINE_MIN)
    kind[line] = LINE
    shade[line] = band[line]
    on = np.zeros(a.shape, bool)
    for r in ladder:
        m = grey & ~line & (np.abs(g - r) <= MERGE_GAP)
        on |= m
        kind[m] = FLOOR
        shade[m] = r
        step[m] = int(np.where(ladder == r)[0][0]) - base_i
    off = grey & ~line & ~on
    n, lab, st, _ = cv2.connectedComponentsWithStats(off.astype(np.uint8), 8)
    dist = cv2.distanceTransform(off.astype(np.uint8), cv2.DIST_L2, 5)
    terrain = np.zeros(n, bool)
    for i in range(1, n):
        if st[i, 4] < MIN_REGION * a.sum():
            continue
        terrain[i] = dist[lab == i].max() >= MIN_RADIUS * side / 2048.0
    coherent, stray = off & terrain[lab], off & ~terrain[lab]
    dark = g < base - MERGE_GAP
    kind[coherent] = np.where(dark[coherent], SHADOW, RAMP)
    shade[coherent] = band[coherent]
    step[coherent] = np.where(dark[coherent], -1, ordinal(g[coherent]))
    if stray.any():
        gs = g[stray]
        snap = np.abs(gs[:, None] - ladder[None, :]).min(1) <= SNAP_MAX
        k_s = np.where(snap, FLOOR, np.where(gs < base - MERGE_GAP, SHADOW, LINE))
        kind[stray] = k_s
        shade[stray] = np.where(snap, ladder[np.abs(gs[:, None] - ladder[None, :]).argmin(1)],
                                band[stray])
        step[stray] = np.where(snap, ordinal(gs), np.where(k_s == SHADOW, -1, 0))
    if site.any():
        srungs = _rungs(g, site, flat, kern)
        sbase_i = int(np.argmax([(site & (np.abs(g - r) <= MERGE_GAP)).sum() for r in srungs]))
        idx = np.abs(g[site, None] - srungs[None, :]).argmin(1)
        kind[site] = SITE
        shade[site] = srungs[idx]
        step[site] = (idx - sbase_i).astype(np.int8)
    return kind, shade, step, ladder, base


def shade_layers(kind, shade, step, M: np.ndarray, shape, clip=None):
    """Warp art-space classes into widget pixels through the 2x3 `M` (crop px
    -> widget px), one winner per pixel by AREA coverage: each class mask is
    box-filtered over one widget pixel's footprint, then sampled bilinearly.
    `clip` multiplies the coverage."""
    s = float(np.sqrt(abs(np.linalg.det(M[:, :2]))))
    b = max(1, int(round(1.0 / s)))
    best = np.zeros(shape, np.float32)
    total = np.zeros(shape, np.float32)
    o_kind = np.zeros(shape, np.uint8)
    o_shade = np.zeros(shape, np.uint8)
    o_step = np.zeros(shape, np.int8)
    classes = np.unique(np.stack([kind[kind > 0], shade[kind > 0],
                                  step[kind > 0].astype(np.uint8)]), axis=1)
    for k, sh, t in classes.T:
        m = ((kind == k) & (shade == sh) & (step.astype(np.uint8) == t)).astype(np.float32)
        cov = cv2.warpAffine(cv2.blur(m, (b, b)), M, (shape[1], shape[0]),
                             flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=0)
        if clip is not None:
            cov *= clip
        total += cov
        win = cov > best
        best[win] = cov[win]
        o_kind[win] = k
        o_shade[win] = sh
        o_step[win] = np.int8(t)
    on = total >= COVER_MIN
    o_kind[~on] = VOID
    o_shade[~on] = 0
    o_step[~on] = 0
    purity = np.zeros(shape, np.uint8)
    purity[on] = np.clip(best[on] / total[on] * 255.0, 0, 255).astype(np.uint8)
    return o_shade, o_kind, o_step, purity


def classify_art(kind):
    """The geometry classes from the art's classes.

        art VOID                     -> VOID, or HOLE where the floor encloses it
        art FLOOR / RAMP / SHADOW    -> FLOOR   (a ramp and a shadow are ground)
        art SITE                     -> PLANT   (a site is painted FLOOR)
        art LINE, void on one side   -> BORDER  (the map's outer boundary)
        art LINE, playable both sides-> BOXEDGE (an interior wall; stops a ray)
    """
    from .minimap import BORDER, BOXEDGE, FLOOR as G_FLOOR, HOLE, PLANT, VOID as G_VOID
    out = np.full(kind.shape, G_VOID, np.uint8)
    out[np.isin(kind, (FLOOR, RAMP, SHADOW, SITE))] = G_FLOOR
    out[kind == SITE] = PLANT
    ff = (kind > 0).astype(np.uint8)
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 1)
    exterior = (ff == 1) & (kind == 0)
    out[(kind == 0) & ~exterior] = HOLE
    line = kind == LINE
    touches_void = cv2.dilate(exterior.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    out[line & touches_void] = BORDER
    out[line & ~touches_void] = BOXEDGE
    return out


# ---------------------------------------------------------------- transform

@lru_cache(maxsize=1)
def _profiles_text() -> str:
    return PROFILES_FILE.read_text(encoding="utf-8") if PROFILES_FILE.is_file() else "{}"


def transforms() -> dict:
    return json.loads(_profiles_text())


def transform(name: str) -> dict:
    P = transforms()
    if name not in P:
        raise SystemExit(f"profile {name!r} has no fitted transform in {PROFILES_FILE.name} "
                         f"-- fit it on a capture of that profile ({', '.join(sorted(P))} are fitted)")
    return P[name]


def map_affine(rot: float, scale: float, centre, side: int = 1024) -> np.ndarray:
    """Texture px -> widget px: turn by `rot` and scale about the texture's
    centre, which lands on `centre`."""
    c = (side - 1) / 2.0
    M = cv2.getRotationMatrix2D((c, c), rot, scale)
    M[:, 2] += np.asarray(centre, float) - c
    return M


def draw(tex: np.ndarray, M: np.ndarray, shape) -> np.ndarray:
    """A premultiplied texture through the render target (`RT_SIDE`): bilinear
    to RT_SIDE, then bilinear into the widget."""
    n = tex.shape[0]
    k = RT_SIDE / n
    S = np.array([[k, 0, (k - 1) / 2.0], [0, k, (k - 1) / 2.0], [0, 0, 1.0]])
    rt = cv2.warpAffine(tex, S[:2], (RT_SIDE, RT_SIDE), flags=cv2.INTER_LINEAR)
    Mr = (np.vstack([M, [0, 0, 1]]) @ np.linalg.inv(S))[:2]
    return cv2.warpAffine(rt, Mr, (shape[1], shape[0]), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def ring(shape, centre, r: float) -> np.ndarray:
    """A two-pixel tent at radius `r` about `centre`."""
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    return np.clip(1.0 - np.abs(np.hypot(xx - centre[0], yy - centre[1]) - r), 0, 1).astype(np.float32)


def disk(shape, centre, r: float) -> np.ndarray:
    """Inside `r`, with a one-pixel ramp."""
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    return np.clip(r + 0.5 - np.hypot(xx - centre[0], yy - centre[1]), 0, 1).astype(np.float32)


def pixel_classes(alpha: np.ndarray, grey: np.ndarray) -> np.ndarray:
    lap = np.abs(cv2.Laplacian(grey, cv2.CV_32F))
    c = np.full(alpha.shape, C_VOID, np.uint8)
    c[alpha > 0.01] = C_EDGE
    core = alpha >= 0.999
    c[core & (lap < 2)] = C_FLAT
    c[core & (lap >= 2)] = C_STRUCT
    return c


def enclosed(alpha: np.ndarray) -> np.ndarray:
    """Void the map surrounds: what a flood from the frame edge cannot reach."""
    ff = (alpha >= 0.01).astype(np.uint8)
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 2)
    return ff == 0


def drawn_layers(map_name: str, prof: str, store=DEFAULT_STORE, P: dict | None = None):
    """Fog and revealed drawn into the profile's widget, clipped at the ring."""
    P = P or transform(prof)
    tx = textures(map_name, store)
    rot = rotation(map_name)
    M = map_affine(rot, P["scale"], P["centre"])
    clip = disk(P["shape"], P["centre"], P["ring_r"])[..., None]
    fog = draw(premultiplied(read_bgra(tx["fog"], store)), M, P["shape"]) * clip
    rev = draw(premultiplied(read_bgra(tx["rev"], store)), M, P["shape"]) * clip
    return fog, rev, M, rot, tx


def composite(layer: np.ndarray, bg: np.ndarray, P: dict) -> np.ndarray:
    a = layer[..., 3:4]
    g = np.asarray(P["gain"], np.float32)
    return layer[..., :3] * 255.0 * g[:, 0] + a * g[:, 1] + (1 - a) * bg


def void_background(alpha: np.ndarray, P: dict) -> np.ndarray:
    """The void model and the ring, per channel (BGR)."""
    v = P["void"]
    f = 1.0 - v["k"] * cv2.GaussianBlur(alpha, (0, 0), v["sigma"])
    f = np.where(enclosed(alpha), f * v["hole"], f)
    bg = np.stack([b * f for b in v["colour"]], axis=2)
    return bg + ring(alpha.shape, P["centre"], P["ring_r"])[..., None] * P["ring_lift"]


# ---------------------------------------------------------------- the world

def site_set(store=DEFAULT_STORE) -> Path:
    return game_dir(store) / "minimap-sites"


@lru_cache(maxsize=4)
def _site_manifest(store: str) -> tuple:
    p = site_set(store) / "manifest.jsonl"
    return tuple(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                 if l.strip()) if p.is_file() else ()


def uidata_constants(map_name: str, store=DEFAULT_STORE) -> dict:
    """The map's world-to-texture constants from its UIData, the numbers
    valorant-api publishes."""
    code = textures(map_name, store)["code"]
    rows = json.loads((game_dir(store) / "minimap" / "ShooterGame" / "Content" / "Maps" / code
                       / f"{code}_UIData.json").read_text(encoding="utf-8"))
    props = next(r.get("Properties") or {} for r in rows
                 if str(r.get("Name", "")).startswith("Default__"))
    return {"x_mult": float(props["XMultiplier"]), "x_add": float(props["XScalarToAdd"]),
            "y_mult": float(props["YMultiplier"]), "y_add": float(props["YScalarToAdd"])}


@lru_cache(maxsize=1)
def _world_text() -> str:
    return WORLD_FILE.read_text(encoding="utf-8") if WORLD_FILE.is_file() else "{}"


def world_offset(map_name: str) -> np.ndarray:
    """The texture px a world position lands from where UIData puts it, per map:
    fitted on development matches (`prototypes/minimap_geometry.py
    --fit-world`). Zero for a map no development match covers."""
    off = (json.loads(_world_text()).get("offsets") or {}).get(map_name)
    return np.asarray(off if off is not None else (0.0, 0.0), float)


def world_to_texture(map_name: str, x, y, store=DEFAULT_STORE):
    """Game units to texture px (pixel centres at integers), as the game places
    a widget drawn at a world position: UIData's constants, then the map's
    world offset."""
    c = uidata_constants(map_name, store)
    u = np.asarray(y, float) * c["x_mult"] + c["x_add"]
    v = np.asarray(x, float) * c["y_mult"] + c["y_add"]
    d = world_offset(map_name)
    return u * 1024.0 - 0.5 + d[0], v * 1024.0 - 0.5 + d[1]


def sites(map_name: str, store=DEFAULT_STORE) -> dict:
    """Site letter -> (world x, world y, the level package that places it): each
    `MinimapSite{A,B,C}` actor's `TheScene.RelativeLocation` in the map's
    gameplay level."""
    import re
    code = textures(map_name, store)["code"]
    out = {}
    for row in _site_manifest(str(store)):
        if row.get("kind") != "json" or f"/Maps/{code}/" not in row["game_path"]:
            continue
        rows = json.loads((site_set(store) / row["output"]).read_text(encoding="utf-8"))
        scene = {str((r.get("Outer") or {}).get("ObjectName", "")).split("PersistentLevel.")[-1]
                 .rstrip("'"): r for r in rows if r.get("Name") == "TheScene"}
        for r in rows:
            m = re.match(r"MinimapSite([ABC])_C$", str(r.get("Type")))
            if m and r["Name"] in scene:
                loc = scene[r["Name"]]["Properties"]["RelativeLocation"]
                out[m.group(1)] = (float(loc["X"]), float(loc["Y"]), row["game_path"])
    return out


def _letter(ch: str, store) -> np.ndarray:
    row = next(r for r in _site_manifest(str(store))
               if r["game_path"].endswith(f"/{ch}Site_Letter.uasset"))
    im = cv2.imread(str(site_set(store) / row["output"]), cv2.IMREAD_UNCHANGED)
    return im[..., 3].astype(np.float32) / 255.0


def letter_cover(map_name: str, M: np.ndarray, shape, store=DEFAULT_STORE) -> np.ndarray:
    """How much each widget pixel the site letters darken, 0..LETTER_OPACITY.
    Each letter is a black glyph (`<X>Site_Letter`), upright, centred on its
    site's world position, `LETTER_TEX_PX` texture px a side, box-filtered
    then warped bilinearly."""
    cover = np.zeros(shape, np.float32)
    s = float(np.sqrt(abs(np.linalg.det(M[:, :2]))))
    for ch, (x, y, _src) in sorted(sites(map_name, store).items()):
        a = _letter(ch, store)
        tx, ty = world_to_texture(map_name, x, y, store)
        cx, cy = M @ np.array([float(tx), float(ty), 1.0])
        k = LETTER_TEX_PX * s / a.shape[0]
        b = max(1, int(round(1.0 / k)))
        W = np.array([[k, 0, cx - k * (a.shape[1] - 1) / 2], [0, k, cy - k * (a.shape[0] - 1) / 2]])
        cover = np.maximum(cover, cv2.warpAffine(cv2.blur(a, (b, b)), W, (shape[1], shape[0]),
                                                 flags=cv2.INTER_LINEAR))
    return cover * LETTER_OPACITY


def asset_stamp(map_name: str, prof: str, store=DEFAULT_STORE) -> str:
    """This file's code (line endings normalised), the two textures' and the
    site levels' sha256, the map's rotation and world offset and the profile's
    transform: `built_by`."""
    h = hashlib.sha256()
    h.update("\n".join(Path(__file__).read_text(encoding="utf-8").splitlines()).encode())
    tx = textures(map_name, store)
    h.update(f"{BUILD}|{tx['fog']['sha256']}|{tx['rev']['sha256']}|{rotation(map_name)}".encode())
    h.update(json.dumps(transform(prof), sort_keys=True).encode())
    h.update(json.dumps(world_offset(map_name).tolist()).encode())
    for row in _site_manifest(str(store)):
        if f"/Maps/{tx['code']}/" in row["game_path"] or "Site_Letter" in row["game_path"]:
            h.update(row["sha256"].encode())
    return h.hexdigest()


def _old_fit(map_name: str, M: np.ndarray, rot: float, store) -> np.ndarray:
    """`shade_fit` in the wiki art's crop convention (`prototypes/wiki_map.py`
    `_warp`/`_place`), so its three readers -- `geometry.map_scale`,
    `raised_edges.zoom` and the Riot `MapFrame` -- read it unchanged. The wiki
    art is the fog texture, upscaled to 2048 px for five maps. It places the
    WORLD, so it carries the map's `world_offset` on top of `M`; `map_affine`
    places the texture. The IoU and NCC slots hold 1.0: the placement is the
    profile's, not a fit. Without the art the scale and offset slots are NaN."""
    art = cv2.imread(str(Path(store) / "reference" / "maps" / f"{map_name}.png"),
                     cv2.IMREAD_UNCHANGED)
    if art is None:
        return np.array([rot, np.nan, np.nan, np.nan, 1.0, 1.0], np.float32)
    k = art.shape[0] / 1024.0
    sc = float(np.sqrt(abs(np.linalg.det(M[:, :2])))) / k
    ys, xs = np.where(art[:, :, 3] > ALPHA_MIN)
    h0, w0 = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    side = int(max(h0, w0) * sc * 1.6)
    R = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, sc)
    R[0, 2] += side / 2 - w0 / 2
    R[1, 2] += side / 2 - h0 / 2
    t = np.array([511.5, 511.5])
    q = k * t + (k - 1) / 2.0 - np.array([xs.min(), ys.min()])
    d = (M @ np.array([*t, 1.0])) - (R @ np.array([*q, 1.0])) + M[:, :2] @ world_offset(map_name)
    return np.array([rot, sc, d[0], d[1], 1.0, 1.0], np.float32)


def render(map_name: str, prof: str, store=DEFAULT_STORE, P: dict | None = None) -> dict:
    """Every asset-derived field of one `(map, profile)` key, as the npz holds them."""
    from .profiles import get_profile
    P = P or transform(prof)
    fog, rev, M, rot, tx = drawn_layers(map_name, prof, store, P)
    a = fog[..., 3]
    bg = void_background(a, P)
    lo_bgr, hi_bgr = composite(fog, bg, P), composite(rev, bg, P)
    static = np.clip(np.rint(lo_bgr), 0, 255).astype(np.uint8)
    lo = cv2.cvtColor(np.clip(lo_bgr, 0, 255).astype(np.float32), cv2.COLOR_BGR2GRAY)
    hi = cv2.cvtColor(np.clip(hi_bgr, 0, 255).astype(np.float32), cv2.COLOR_BGR2GRAY)
    cls = pixel_classes(a, cv2.cvtColor(fog[..., :3] * 255.0, cv2.COLOR_BGR2GRAY))
    lo[cls == C_VOID] += P["void_lo"]
    hi[cls == C_VOID] += P["void_hi"]
    keep = 1.0 - letter_cover(map_name, M, P["shape"], store)
    static = np.clip(np.rint(np.clip(lo_bgr, 0, 255) * keep[..., None]), 0, 255).astype(np.uint8)
    lo, hi = lo * keep, hi * keep
    im = read_bgra(tx["fog"], store)
    kind, shade, step, _ladder, _base = art_classes(im, map_name)
    ys, xs = np.where(im[:, :, 3] > ALPHA_MIN)
    Mc = M.copy()
    Mc[:, 2] += M[:, :2] @ np.array([xs.min(), ys.min()], float)
    o_shade, o_kind, o_step, purity = shade_layers(
        kind, shade, step, Mc, P["shape"], disk(P["shape"], P["centre"], P["ring_r"]))
    x0, y0, x1, y1 = next(r for r in get_profile(prof).rois
                          if r.name == "minimap").pixels(*P["frame"])
    st = asset_stamp(map_name, prof, store)
    prov = {"build": BUILD, "fog": tx["fog"]["game_path"], "fog_sha256": tx["fog"]["sha256"],
            "revealed": tx["rev"]["game_path"], "revealed_sha256": tx["rev"]["sha256"],
            "rotation": rot, "transform": prof, "transform_fit_on": list(TRAIN_KEYS),
            "sites": {k: list(v) for k, v in sites(map_name, store).items()},
            "world_offset_tex_px": world_offset(map_name).round(4).tolist()}
    return dict(labels=classify_art(o_kind), static=static, roi=np.array([x0, y0, x1, y1]),
                lo_gray=lo.astype(np.float32), hi_gray=hi.astype(np.float32),
                sd_lo=np.asarray(P["sd_lo"], np.float32)[cls],
                sd_hi=np.asarray(P["sd_hi"], np.float32)[cls],
                built_from=np.array(f"game-files:{BUILD}"), label_source=np.array("official"),
                built_by=np.array(st), map_affine=M.astype(np.float64),
                provenance=np.array(json.dumps(prov, sort_keys=True)),
                shade=o_shade, shade_kind=o_kind, shade_step=o_step, shade_purity=purity,
                shade_fit=_old_fit(map_name, M, rot, store), shade_map=np.array(map_name),
                shade_built_by=np.array(st))
