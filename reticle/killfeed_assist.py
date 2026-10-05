"""Stage 02: the killfeed assist panel, read from the game's own art.

An assisted kill draws, left of the killer's portrait, each assister's
portrait with the assisting ability's icon to its right
[domain:killfeed/assist-panel]; the panel fills the band's top 18 rows
[domain:killfeed/assist-panel-layout]. The game's widgets fix the geometry
[domain:killfeed/assist-panel-widget]: `KillFeed_AssisterPortraits` holds four
`WBP_KillFeedAssister` slots in one horizontal box; each draws its
`AssistPortrait` brush at 36 x 18 px, then, when visible, its
`EquippableImage` at 14 x 14 px, centred, with 2 px of padding to its right.
The icon starts collapsed, so an assister with no icon is a portrait alone
[domain:killfeed/assist-without-icon].

**What this reads.** Only entries the killfeed reader found: for each view of
an entry's killer (a `killfeed_portrait` killer row), the panel is searched
from the killer art's left edge leftwards, one assister at a time, never over
the whole row. The edge is first checked against the killer's own art
(`check_anchor`): the killfeed reader's priors are scored with the death
verdict's killer (or, unnamed, the side's five), and where none confirms it
the search widens to the entry's band, then to every row of the crop (the
reader's row can be a portrait off). A disagreement with the killfeed
reader's first prior is stored (`upstream_disagrees`, `upstream_row_off`)
for its owner; the killfeed reader itself is not changed here. A view whose
edge no killer art confirms refuses its count (`anchor_unverified`): a walk
from the wrong place reads an absence it never saw. Each step scores the side's
portrait art (`appearance.art_zncc`, the art shrunk to the brush's 36 x 18
with `INTER_AREA`) at every column where the assister's right edge can sit:
against the panel's right end with no icon, or one icon cell (16 px) further
left. The best placement says whether an icon cell lies between the portrait
and the panel's right end; the next assister ends where this one begins.

**Absence is a reading.** Where no candidate's art correlates at
`PRESENT_Z` the step reads "no assister": the panel holds `count` assisters.
Before reading absence the step tries, on the player's side, the same art
with the player's yellow frame unweighted (`FRAME_MARGIN`,
[domain:killfeed/self-yellow-frame]), then every agent with art (the surprise
path): a portrait that only an agent outside the side matches is stored as
present with `widened`, and its agent stays for the arbiter to refuse. A
step no art clears but whose best window shows a drawn portrait cell (the
plate and crisp upper and lower edges, `portrait_drawn`) is an assister no
agent's art recognises: it counts, and names nobody (`UNRECOGNISED`);
presence and identity are separate questions. A step whose search the
ROI's left edge cuts stops with `count` None and `count_min`; an absence read
within `EMPTY_VISIBLE_MIN` of that edge is flagged. Up to four assisters is the
player's belief [domain:killfeed/assist-panel-four-assisters-belief].

**Icons.** An icon cell is read as soft whiteness (each pixel's least channel
over 255: the white glyph over the translucent plate) against the game's
ability icons (each ability UIData's `DisplayIcon`, alpha shrunk to 14 px with
`INTER_AREA` at sub-pixel phases), scored by `killfeed_numeral.fit_scores`:
the share of the window's variance that `background + contrast * glyph`
explains. The reader scores the icons of the agents its caller admits (the
killer's side, from the lineup) and the panel's own generic icons
(`TX_Kilfeed_Assist_*`, `TX_Assist_Resurrection`); where none reaches
`ICON_SURPRISE`, it widens to every ability icon in the build. It names no
ability: `adjudication.assist` restricts the scores to the assister's kit.

**Measured** (`prototypes/assist_panel_eval.py`, 3 views per entry, against
Riot's assist credit on paired deaths). Versions 0.1.0-0.4.0 were chosen
against all 21 Riot matches; from 0.5.0 the matches are split by a fixed hash
into a dev half (10, used for choices with the player's labels) and a
held-out half (11, scored once per version; 0.6.0 is its second use, after
a review had named five of its cases; 0.6.1 changes none of its 1652
verdicts and is not scored there). On the held-out half, where the
count is read, presence agrees with Riot's assisted kill at precision
[metric:assist_panel/riot_held#presence_precision=0.9971] and recall
[metric:assist_panel/riot_held#presence_recall=0.9971]; a named assister is
one Riot credits at [metric:assist_panel/riot_held#assister_precision=0.9944],
and the player's own assists are named at
[metric:assist_panel/riot_held#assistant_own_recall=0.9804]. Astra on
223d636bf8d2 is drawn from art the build's texture does not hold
[domain:killfeed/portrait-art-variants]: of the dev half's 12 Riot Astra
assists, [metric:assist_panel/riot_dev#assistant_astra_unrecognised=11] read
as an unrecognised portrait, present and unnamed, and one is named. The ROI's left edge cuts
the panel of a long killer name; those deaths keep a lower bound.

Game art is loaded from the store's game-file reference (`ICON_BUILD`), never
copied into this repository: the portraits are each agent UIData's
`KillfeedPortrait` (`game_portrait_paths`).

Owns [owns:killfeed-assist-panel].
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

import cv2

from . import appearance
from .killfeed import (ART_PRIOR_X, ART_PRIOR_Y, ART_SURPRISE_Z, ART_TILE_H, ART_WIDE_Y,
                       KILLER_ART_FROM_PLATE, PLATE_EDGE_MIN, PORTRAIT_ASPECT,
                       KillfeedScale, plate_score)
from .killfeed_numeral import fit_scores, slot_whiteness

# 0.1.0 (2026-10-04): first reader.
# 0.2.0 (2026-10-04): a portrait needs the plate behind its transparent
# pixels (`PLATE_SHARE_MIN`); the killer art's left edge is tried by prior
# (entry anchor, plate's left end, art window), a later one only where an
# earlier reads no panel.
# 0.3.0 (2026-10-04): presence at art ZNCC 0.65 (`PRESENT_Z`); the plate
# share is stored, not gated (`PLATE_SHARE_MIN`).
# 0.4.0 (2026-10-04): a window the ROI's left edge cuts is scored on its
# visible columns, at least `ART_MIN_VISIBLE`; fewer stop the walk as cut.
# 0.5.0 (2026-10-04): the portrait art is the build's own (each agent
# UIData's `KillfeedPortrait`, `game_portrait_paths`), equal to valorant-api's
# within 2/255; icons come from every ability UIData's `DisplayIcon`, which
# adds Miks' M-pulse and Phoenix's Run it Back. The killer art's left edge is
# checked against the killer's own art before the walk (`check_anchor`): a
# prior the art does not confirm widens to the entry's band, and a
# disagreement with the killfeed reader's anchor is stored. A step no side
# portrait fills is scored again with the player's yellow frame unweighted
# (`FRAME_MARGIN`) on the player's side. The stream opens with a summary row.
# 0.6.0 (2026-10-04): where the priors and the band hold no killer art, the
# killer's art is searched over every row of the crop (`ANCHOR_ROWS`, the
# peak nearest the prior's row); the upstream row error is stored
# (`upstream_row_off`). A view whose anchor stays unverified or unchecked
# refuses its count (`anchor_unverified`, `anchor_unchecked`) and keeps its
# walk as `unverified_read`. A step no agent's art clears but which shows a
# drawn portrait cell (`portrait_drawn`) counts as an unnamed assister
# (`UNRECOGNISED`); each step stores what its best window shows
# (`step_evidence`); an absence read within `EMPTY_VISIBLE_MIN` px of the
# ROI's left edge is flagged (`within_visible_min`), not refused.
# 0.6.1 (2026-10-04): the drawn rule is measured at the best placement under
# each edge prediction (with an icon, without), not only at the argmax over
# both (`_stop_evidence` `predictions`, `drawn_by`); a step is drawn if either
# fires.
KILLFEED_ASSIST_VERSION = "killfeed-assist-0.6.1"

#: The game build whose widgets and textures this reader draws on.
ICON_BUILD = "release-13.06-shipping-18-5590001"

# --- geometry, base px at 1080 (the build's widget JSON) ---------------------
#: `AssistPortrait`'s brush (`WBP_KillFeedAssister`): 36 x 18.
PORTRAIT_W = 36
PORTRAIT_H = 18
#: `EquippableImage`'s brush, 14 x 14, and its slot's right padding, 2.
ICON_PX = 14
ICON_PAD = 2
#: One icon cell: the icon and its padding.
ICON_CELL = ICON_PX + ICON_PAD
#: `KillFeed_AssisterPortraits` holds four assister slots.
MAX_ASSISTERS = 4
#: The art's unweighted border (base px): the player's own assister is framed
#: in yellow [domain:killfeed/self-yellow-frame]; the killer art's 4 px of 34,
#: scaled to the 18 px brush.
ART_MARGIN = 2
#: The unweighted border (base px) of the player's own assister. The game
#: draws `MeBorder` (`M_UI_KillfeedBorder`, tint E7EC77, and the
#: `TX_Killfeed_MeBorder` chevron) over the panel when the local player
#: assisted (`KillFeed_AssisterPortraits`, `bLocalPlayerIsAssister`)
#: [domain:killfeed/self-yellow-frame]; the frame covers about three pixels
#: of the portrait's edge. On three of the dev half's five self-framed
#: misses (ff636d173b07 233.0 s and 2073.0 s, a1a995e6b19b 1231.0 s) the
#: player's agent scored 0.57-0.66 at 2 px and 0.74-0.80 at 3 px over
#: brush sizes 34-36 px wide; the framed path's picks on the dev half had a
#: median correlation of 0.70 (15 views). Chosen on the dev half.
FRAME_MARGIN = 3

# Where an assister's right edge sits, relative to the right end it abuts
# (the killer art's left edge, or the previous assister's left edge). On 81
# labelled assisted entries the portrait's right edge sat -1 px (0 to -2)
# from the killer art's left edge with no icon, -16 to -17 with one. Against
# checked anchors (`check_anchor`) on five dev matches the first assister's
# edge sat at 0 (no icon) and -16 (icon), each +-1: inside the search.
#: The right edge's search, base px either side of the two predictions.
EDGE_NO_ICON = -1
EDGE_ICON = EDGE_NO_ICON - ICON_CELL
EDGE_SEARCH = 3
#: Rows searched about the killer art's top (base px).
ROW_SEARCH = 1
#: An icon cell lies between the portrait and the right end when the gap is
#: at least this (base px): half an icon cell.
ICON_GAP_MIN = ICON_CELL / 2

#: A portrait is present when its best art correlation reaches this. The
#: killer portrait's cut (`killfeed.ART_SURPRISE_Z`, 0.5) is too low for the
#: 36 x 18 tile: on the player's labelled entries (dev set) the reader's
#: picks with the gate off scored 0.695 at the 5th percentile where a
#: portrait was drawn, and up to 0.648 (one at 0.725) on background, most
#: of those from the all-agent widening; 0.65 kept 230 of 240 true picks and
#: 1 of 55 false. It was chosen after 0.1.0's Riot score (0.5 failed its
#: registered precision), so Riot's 21 matches were dev data for it; the
#: held-out half of `prototypes/assist_panel_eval.py`'s split checks it from
#: 0.5.0 on.
PRESENT_Z = 0.65

#: The least soft plate share (`killfeed.plate_score`) over a portrait's
#: transparent pixels. Stored, not gated: on the same labels true picks had a
#: median share of 0.45 and a tenth under 0.04 (the panel's backing is
#: translucent), so the share separates worse than the art (0.2.0 gated at
#: 0.5 and lost two thirds of Riot's assisted kills). None disables the gate.
PLATE_SHARE_MIN = None
#: An art whose transparent inner pixels are under this share of its tile
#: shows too little plate to judge; its placement passes on the art alone.
PLATE_AREA_MIN = 0.08
#: The fewest art columns (base px) inside the ROI a cut assist window is
#: scored on: half the brush. The killer's 22 of 68 columns
#: (`killfeed.ART_MIN_VISIBLE`) was measured on the larger tile; half is
#: chosen, not measured; the held-out half checks it.
ART_MIN_VISIBLE = PORTRAIT_W // 2
#: Placements over PRESENT_Z checked for the plate, best first.
PICK_MAX = 24

#: Icon search: base px either side of the predicted icon box.
ICON_SEARCH = 2
#: Sub-pixel phases per axis of each icon template.
ICON_PHASES = 3
#: Below this best score among the admitted icons the reader widens to every
#: ability icon in the build.
ICON_SURPRISE = 0.5

#: Refusals and stops.
REFUSE_NO_ANCHOR = "no_killer_art"
#: The killer's art confirmed no prior, in the band or any row.
REFUSE_UNVERIFIED = "anchor_unverified"
#: Neither the death's killer nor the killer's side is known to check with.
REFUSE_UNCHECKED = "anchor_unchecked"
STOP_ABSENT = "no_portrait"
STOP_CUT = "cut_by_roi"
STOP_FULL = "max_slots"

#: The panel's own icons, by name: generic assist kinds and the revive icon.
GENERIC_ICONS = {
    "assist:Buff": "KillFeed_Assists/Textures/KillfeedIcons/TX_Kilfeed_Assist_Buff.png",
    "assist:Damage": "KillFeed_Assists/Textures/KillfeedIcons/TX_Kilfeed_Assist_Damage.png",
    "assist:Utility": "KillFeed_Assists/Textures/KillfeedIcons/TX_Kilfeed_Assist_Utility.png",
    "assist:Resurrection": "Textures/AssistTextures/TX_Assist_Resurrection.png",
}
_KILLCALLOUT = "killfeed-icons/ShooterGame/Content/UI/InGame/HUD/KillCallout/"


def icon_build_dir(store_root) -> Path:
    return Path(store_root) / "reference" / "game-files" / ICON_BUILD


def _export_props(path: Path) -> list[dict]:
    """Every export's `Properties` in one exported package JSON."""
    if not path.is_file():
        return []
    return [obj.get("Properties") or {} for obj in json.loads(path.read_text(encoding="utf-8"))]


def _display_name(path: Path) -> str | None:
    for p in _export_props(path):
        name = (p.get("DisplayName") or {}).get("LocalizedString")
        if name:
            return name
    return None


def _game_png(d: Path, object_path: str) -> Path:
    """The export's PNG of a `/Game/...` texture object path."""
    rel = object_path.replace("/Game/", "ShooterGame/Content/", 1).rsplit(".", 1)[0]
    return d / "killfeed-icons" / f"{rel}.png"


def _characters(store_root) -> Path:
    return icon_build_dir(store_root) / "ability-data" / "ShooterGame" / "Content" / "Characters"


#: Character folders whose UIData is no playable agent's own.
UIDATA_SKIP = ("AbilityDraftAgent",)


def _agent_names(store_root) -> dict[str, str]:
    """{character folder: agent name}: each agent UIData's `DisplayName`,
    KAY/O spelt KAY_O as the lineup spells it."""
    out = {}
    chars = _characters(store_root)
    if not chars.is_dir():
        return out
    for c in sorted(chars.iterdir()):
        if c.name in UIDATA_SKIP:
            continue
        name = _display_name(c / f"{c.name}_UIData.json")
        if name:
            out[c.name] = name.replace("/", "_")
    return out


@lru_cache(maxsize=4)
def game_portrait_paths(store_root: str) -> tuple[dict, dict]:
    """({agent: png}, provenance): each agent UIData's `KillfeedPortrait`
    texture as the build's `killfeed-icons` export holds it. The assist
    portrait and the killer's art are this texture
    [domain:killfeed/assist-panel-widget]; valorant-api's killfeed portraits
    equal it within 2/255 per channel (Astra, Sage, Jett, KAY/O, Omen
    compared). Empty when the store holds no export."""
    d = icon_build_dir(store_root)
    out, missing = {}, []
    for code, agent in _agent_names(store_root).items():
        for p in _export_props(_characters(store_root) / code / f"{code}_UIData.json"):
            ref = (p.get("KillfeedPortrait") or {}).get("ObjectPath")
            if not ref:
                continue
            png = _game_png(d, ref)
            if png.is_file():
                out.setdefault(agent, png)
            else:
                missing.append(ref)
    return out, {"build": ICON_BUILD, "source": "UIData KillfeedPortrait",
                 "agents": len(out), "missing": missing}


@lru_cache(maxsize=4)
def icon_art(store_root: str) -> tuple[dict, dict]:
    """({name: path}, provenance) of every icon the panel can draw: the
    `DisplayIcon` of each ability UIData (`UIData_*`, `AbilityUIData_*`) of
    every agent that the build's `killfeed-icons` export holds, named
    `<Agent>/<ability>` (the agent's own UIData `DisplayName`, KAY/O spelt
    KAY_O as the lineup spells it; the ability's UIData `DisplayName`), and
    `GENERIC_ICONS`. Empty when the store holds no export."""
    d = icon_build_dir(store_root)
    chars = _characters(store_root)
    if not (d / "killfeed-icons").is_dir() or not chars.is_dir():
        return {}, {"build": ICON_BUILD, "reason": "no_game_icons"}
    out, missing = {}, []
    for code, agent in _agent_names(store_root).items():
        for f in sorted((chars / code).rglob("*UIData_*.json")):
            if f.name == f"{code}_UIData.json":
                continue
            for p in _export_props(f):
                ref = (p.get("DisplayIcon") or {}).get("ObjectPath")
                ability = (p.get("DisplayName") or {}).get("LocalizedString")
                if not ref or not ability:
                    continue
                png = _game_png(d, ref)
                if png.is_file():
                    out.setdefault(f"{agent}/{ability}", png)
                else:
                    missing.append(ref)
    for name, rel in GENERIC_ICONS.items():
        png = d / _KILLCALLOUT / rel
        if png.is_file():
            out[name] = png
        else:
            missing.append(rel)
    return out, {"build": ICON_BUILD, "icons": len(out), "missing": sorted(set(missing))}


def _icon_stack(png: Path, px: float) -> np.ndarray | None:
    """One icon's alpha drawn at `px` capture px square, at every sub-pixel
    phase: (ICON_PHASES**2, n, n) float32 0..1, padded by one empty px. The
    128 px texture is shrunk with `INTER_AREA`, then moved by a linear warp."""
    im = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        return None
    a = im[:, :, 3].astype(np.float32) / 255.0
    n = max(4, int(round(px)))
    drawn = np.pad(cv2.resize(a, (n, n), interpolation=cv2.INTER_AREA), 1)
    out = []
    for j in range(ICON_PHASES):
        for i in range(ICON_PHASES):
            m = np.float32([[1, 0, i / ICON_PHASES], [0, 1, j / ICON_PHASES]])
            out.append(cv2.warpAffine(drawn, m, drawn.shape[::-1], flags=cv2.INTER_LINEAR))
    return np.stack(out).astype(np.float32)


@lru_cache(maxsize=8)
def icon_templates(store_root: str, scale: float = 1.0) -> dict[str, np.ndarray]:
    """{name: phase stack} for every icon of `icon_art`, drawn at the
    capture's scale times `ICON_PX`. Built once per store and scale."""
    arts, _prov = icon_art(store_root)
    out = {}
    for name, png in arts.items():
        st = _icon_stack(png, ICON_PX * float(scale))
        if st is not None and float(st.max()) > 0.1:
            out[name] = st
    return out


_GAME_ART: dict = {}


def _game_art(store_root, h: int, w: int, margin: int) -> "appearance.ArtTiles | None":
    key = (str(store_root), int(h), int(w), int(margin))
    if key not in _GAME_ART:
        paths, _prov = game_portrait_paths(str(store_root))
        _GAME_ART[key] = appearance.art_tiles(paths, h, w, margin) if paths else None
    return _GAME_ART[key]


def portrait_art(store_root, s: KillfeedScale,
                 margin: int = ART_MARGIN) -> "appearance.ArtTiles | None":
    """The build's killfeed portraits (`game_portrait_paths`) at the assist
    brush's size, in Lab, with a `margin`-px unweighted border (base px):
    `ART_MARGIN`, or `FRAME_MARGIN` for the player's framed portrait."""
    return _game_art(store_root, s.n(PORTRAIT_H), s.n(PORTRAIT_W), s.n(margin))


def killer_art(store_root, s: KillfeedScale) -> "appearance.ArtTiles | None":
    """The same portraits at the killer's tile (`killfeed.ART_TILE_H`, two
    wide, `appearance.ART_INNER_MARGIN` unweighted), to check where the
    killer's art starts (`check_anchor`)."""
    th = s.n(ART_TILE_H)
    return _game_art(store_root, th, int(round(PORTRAIT_ASPECT * th)),
                     s.n(appearance.ART_INNER_MARGIN))


def _portrait_step(crop_lab: np.ndarray, right: float, top: float, s: KillfeedScale,
                   art, names: list[str]):
    """Score `names` at every right edge the step allows. Returns ((z per
    candidate (rows, cols, n), xs (window left columns), ya) or None when the
    ROI holds no window, cut). A window the ROI's left edge cuts is scored on
    its columns inside (`appearance.art_zncc` `cut`) when at least
    `ART_MIN_VISIBLE` remain; `cut` says some placement had fewer."""
    h, w = crop_lab.shape[:2]
    tw, th = art.w, art.h
    lo = int(np.floor(right + s.px(EDGE_ICON - EDGE_SEARCH))) - tw
    hi = int(np.ceil(right + s.px(EDGE_NO_ICON + EDGE_SEARCH))) - tw
    ya = max(0, int(round(top)) - s.n(ROW_SEARCH))
    yb = min(h, int(round(top)) + th + s.n(ROW_SEARCH))
    vmin = s.n(ART_MIN_VISIBLE)
    cut = lo + tw < vmin
    hi = min(w - tw, hi)
    if yb - ya < th:
        return None, cut
    parts, xs = [], []
    for x in range(max(lo, vmin - tw), min(0, hi + 1)):
        parts.append(appearance.art_zncc(crop_lab[ya:yb, :tw + x], art, names, cut=-x))
        xs.append(x)
    a = max(0, lo)
    if hi >= a:
        parts.append(appearance.art_zncc(crop_lab[ya:yb, a:hi + tw], art, names))
        xs.extend(range(a, hi + 1))
    if not xs:
        return None, cut
    return (np.concatenate(parts, axis=1), np.asarray(xs), ya), cut


def read_icon(crop: np.ndarray, x0: float, y0: float, s: KillfeedScale,
              temps: dict[str, np.ndarray], admitted: list[str]) -> dict:
    """Score the icon cell whose box would start at (x0, y0) ROI px against
    the `admitted` icons, widening to every icon on surprise. Returns the
    scores (rounded, best first, at most 12), the best, the search mode and
    where the best sat."""
    h, w = crop.shape[:2]
    names = [n for n in admitted if n in temps]
    if not names:
        names = list(temps)
    any_t = next(iter(temps.values()))
    th, tw = any_t.shape[1:]
    sx = s.n(ICON_SEARCH)
    bx0, by0 = int(np.floor(x0)) - 1 - sx, int(np.floor(y0)) - 1 - sx
    bx1, by1 = bx0 + tw + 2 * sx + 1, by0 + th + 2 * sx + 1
    if bx0 < 0 or by0 < 0 or bx1 > w or by1 > h:
        return {"icon_scores": None, "icon_reason": STOP_CUT}
    win = slot_whiteness(crop[by0:by1, bx0:bx1])

    def score(ns):
        got = {}
        for n in ns:
            sc, (k, y, x) = fit_scores(win, temps[n])
            got[n] = (float(sc[k, y, x]), (int(x) + bx0, int(y) + by0))
        return got

    got = score(names)
    mode = "admitted"
    if max(v[0] for v in got.values()) < ICON_SURPRISE and len(names) < len(temps):
        got.update(score([n for n in temps if n not in got]))
        mode = "all_icons"
    ranked = sorted(got.items(), key=lambda kv: -kv[1][0])
    best, (bs, (bx, by)) = ranked[0]
    return {"icon_scores": {n: round(v[0], 4) for n, v in ranked[:12]},
            "icon_best": best, "icon_score": round(bs, 4),
            "icon_margin": round(bs - (ranked[1][1][0] if len(ranked) > 1 else 0.0), 4),
            "icon_search": mode, "icon_at": [bx, by], "icon_reason": None}


def _transparency(art) -> np.ndarray:
    """Per agent, the art's inner transparent weight (1 - alpha inside the
    unweighted border): where the assister's plate shows through."""
    key = id(art)
    if key not in _TRANSPARENT:
        w = art.alpha
        m = art.margin
        inner = np.zeros(w.shape[1:], np.float32)
        inner[m:art.h - m, m:art.w - m] = 1.0
        _TRANSPARENT[key] = ((1.0 - w) * inner[None]).astype(np.float32)
    return _TRANSPARENT[key]


_TRANSPARENT: dict = {}


def _pick(z, xs, ya, names, art, plate):
    """The best (placement, agent) whose art reaches PRESENT_Z and whose
    transparent pixels show the plate: ((agent index, row, col, z, share) or
    None, the best z seen)."""
    best_z = float(z.max()) if z.size else -1.0
    trans = _transparency(art)
    cand = np.argwhere(z >= PRESENT_Z)
    if not len(cand):
        return None, best_z
    order = np.argsort(-z[cand[:, 0], cand[:, 1], cand[:, 2]])[:PICK_MAX]
    for i in order:
        by, bx, ai = (int(v) for v in cand[i])
        tr = trans[art.index[names[ai]]]
        tot = float(tr.sum())
        y, x = ya + by, int(xs[bx])
        if x < 0:   # a cut window: the plate share is not measured
            return (ai, by, bx, float(z[by, bx, ai]), None), best_z
        win = plate[y:y + art.h, x:x + art.w]
        share = float((tr * win).sum() / tot) if tot >= PLATE_AREA_MIN * tr.size else None
        if share is None or PLATE_SHARE_MIN is None or share >= PLATE_SHARE_MIN:
            return (ai, by, bx, float(z[by, bx, ai]), share), best_z
    return None, best_z


def _window_evidence(lab: np.ndarray, plate: np.ndarray, x: int, y: int, art,
                     agent: str) -> dict:
    """What one portrait window (left column `x`, top row `y`, ROI px) shows
    besides the art: the mean plate membership over its visible columns
    (`plate_mean`), the share over `agent`'s transparent pixels
    (`plate_trans`, None where the art shows too little plate), and the
    median Lab step across the window's lower and upper edges
    (`edge_bottom`, `edge_top`; the portrait cell has a crisp lower edge
    [domain:killfeed/assist-panel-layout])."""
    h, w = lab.shape[:2]
    a = max(0, int(x))
    b = min(w, int(x) + art.w)
    out = {"x": int(x), "y": int(y), "agent": agent, "plate_mean": None, "plate_trans": None,
           "edge_bottom": None, "edge_top": None}
    if b - a < 2 or y < 0 or y + art.h > h:
        return out
    out["plate_mean"] = round(float(plate[y:y + art.h, a:b].mean()), 4)
    if agent is not None and agent in art.index:
        tr = _transparency(art)[art.index[agent]][:, a - int(x):b - int(x)]
        tot = float(tr.sum())
        if tot >= PLATE_AREA_MIN * tr.size:
            out["plate_trans"] = round(float((tr * plate[y:y + art.h, a:b]).sum() / tot), 4)
    if y + art.h < h:
        d = np.linalg.norm(lab[y + art.h, a:b] - lab[y + art.h - 1, a:b], axis=-1)
        out["edge_bottom"] = round(float(np.median(d)), 3)
    if y >= 1:
        d = np.linalg.norm(lab[y, a:b] - lab[y - 1, a:b], axis=-1)
        out["edge_top"] = round(float(np.median(d)), 3)
    return out


def _stop_evidence(got, names: list[str], art, lab: np.ndarray, plate: np.ndarray,
                   edge: float, icon_gap: float) -> dict:
    """The step's best placements over the side's art, though under
    `PRESENT_Z`. The top level is the best placement over every agent and
    both edge predictions, with each candidate's best correlation
    (`art_zncc`) and what its window shows (`_window_evidence`), as before
    0.6.1. `predictions` holds the same for the best placement under each
    edge prediction alone (`icon`: an icon cell between the window and
    `edge`, `no_icon`: none), each with its own `art_zncc` and whether the
    drawn rule fires there (`drawn`): one prediction's placement can
    outscore the portrait drawn at the other (223d636bf8d2 411.0 s, a no-icon
    Skye over an iconed Astra). `drawn_by` names the prediction that fires (the higher art first),
    or None; where one fires, the top level is that prediction's window."""
    z, xs, ya = got
    if not z.size:
        return {}
    n = z.shape[2]
    per = z.reshape(-1, n).max(0)
    gap = float(edge) - (np.asarray(xs, np.float64) + art.w)
    preds = {}
    for key, mask in (("icon", gap >= icon_gap), ("no_icon", gap < icon_gap)):
        if not mask.any():
            continue
        zm = z[:, mask, :]
        by, bx, ai = np.unravel_index(int(np.argmax(zm)), zm.shape)
        e = _window_evidence(lab, plate, int(np.asarray(xs)[mask][bx]), int(ya + by), art,
                             names[int(ai)])
        e["art_zncc"] = {a: round(float(v), 4) for a, v in zip(names, zm.reshape(-1, n).max(0))}
        e["drawn"] = portrait_drawn(e)
        preds[key] = e
    order = sorted(preds, key=lambda k: -max(preds[k]["art_zncc"].values()))
    fire = next((k for k in order if preds[k]["drawn"]), None)
    pick = fire or order[0]
    ev = {k: v for k, v in preds[pick].items() if k not in ("art_zncc", "drawn")}
    ev["art_zncc"] = {a: round(float(v), 4) for a, v in zip(names, per)}
    ev["prediction"] = pick
    ev["predictions"] = preds
    ev["drawn_by"] = fire
    return ev


#: A drawn portrait no agent's art clears (`portrait_drawn`); named nobody.
UNRECOGNISED = "portrait not recognised"
#: The rule that calls an unrecognised step drawn: at the side's best
#: placement under either edge prediction (`_stop_evidence`), the art still
#: correlates at `DRAWN_Z_MIN`, the window holds the plate (`plate_mean` at
#: `DRAWN_PLATE_MIN`), and both its upper and lower edges step by
#: `DRAWN_EDGE_MIN` (median Lab distance across the row; the portrait cell is
#: a crisp 36 x 18 box). Chosen on the dev half's stored views (0.6.0
#: features): of 4140 stop steps where the read count and names equal Riot's
#: (true absence), none fires (the nearest: art 0.42 with edges 6.7); of 34
#: views where Riot's Astra is unread, 30 fire; of 1158 recognised portraits
#: 1034 (89%) clear the edge and plate parts. The dev half's one other firing
#: (ff636d173b07 1054.5 s) is the player's framed Phoenix, drawn, which Riot
#: credits. 0.6.1 measures the rule under each edge prediction: on the same
#: dev views (4131 true-absence stops as the 0.6.0 stream stores them) it
#: fires on none, and it fires on all 34 Astra views. In the four 0.6.0
#: missed, the other prediction's placement outscored Astra's and covered
#: no cell: at 223d636bf8d2 411.0 s a no-icon Skye over her iconed cell at
#: x 18, at 1872.0-1873.0 s an iconed Skye at x 7 over her uncut no-icon
#: cell at x 27. 0.6.0 had named a cut Astra and a fading frame.
DRAWN_Z_MIN = 0.4
DRAWN_PLATE_MIN = 0.05
DRAWN_EDGE_MIN = 8.0
#: How far (base px) a step's right end must lie inside the ROI's left edge
#: for its absence to be seen. On 400 recognised portraits in uncut steps
#: (dev half, 40 per match) the ROI's left edge was moved over every column:
#: each portrait was still found while its step's right end lay at least
#: 22 px (no icon) or 46 px (icon) inside; 48 keeps 2 px beyond the worst.
#: The window rule (`ART_MIN_VISIBLE`) already reads absence from 38 px, so
#: this rule calls no cut step empty: 4f207c0c4e39 1783.0 s (right end about
#: 27 px inside) stays cut, since an iconed second assister there would show
#: 10 of its 36 columns. Enforcing it the other way (cutting steps at 38-47
#: px) withdrew 88 dev reads, 79 agreeing with Riot and 9 not (6 of them
#: zeros Riot credits), so it is not enforced: an absence read inside it
#: carries `within_visible_min` for review.
EMPTY_VISIBLE_MIN = 48


def portrait_drawn(ev: dict) -> bool:
    """Whether a step whose art clears no agent still shows a drawn portrait
    cell (`DRAWN_Z_MIN`, `DRAWN_PLATE_MIN`, `DRAWN_EDGE_MIN`)."""
    z = max((ev.get("art_zncc") or {}).values(), default=None)
    pm, eb, et = ev.get("plate_mean"), ev.get("edge_bottom"), ev.get("edge_top")
    if z is None or pm is None or eb is None or et is None:
        return False
    return z >= DRAWN_Z_MIN and pm >= DRAWN_PLATE_MIN and min(eb, et) >= DRAWN_EDGE_MIN


def read_panel(crop: np.ndarray, right: float, top: float, s: KillfeedScale, art,
               candidates: list[str], icon_temps: dict | None = None,
               icons_admitted: list[str] | None = None, framed_art=None,
               lab: np.ndarray | None = None) -> dict:
    """Read the panel left of a killer art whose left edge is `right` and
    top `top` (ROI px). `candidates` are the agents the caller admits (the
    killer's side); the full art set is the surprise path. A portrait is
    present where its art correlation reaches `PRESENT_Z`; the plate share
    behind its transparent pixels is stored (`PLATE_SHARE_MIN`). A step the
    side's art leaves empty is scored again with `framed_art` (the same art
    with `FRAME_MARGIN` unweighted) when the caller passes it, the player's
    side, before the all-agent widening: the player's own portrait carries
    the yellow frame [domain:killfeed/self-yellow-frame]. Returns `count`
    (None with `count_min` where the ROI cuts the search), `assisters`
    (beside the killer first) and `stop` (why the walk ended). `lab` is the
    crop in Lab when the caller holds it."""
    lab = appearance.to_lab(crop) if lab is None else lab
    plate = plate_score(crop)
    names = [c for c in candidates if c in art.index] or list(art.agents)
    out, edge = [], float(right)
    stop = {"reason": STOP_FULL}
    for k in range(MAX_ASSISTERS):
        got, cut = _portrait_step(lab, edge, top, s, art, names)
        widened, frame, cand, hit, best, used = None, None, names, None, -1.0, art
        if got is not None:
            hit, best = _pick(got[0], got[1], got[2], names, art, plate)
        if hit is None and got is not None and framed_art is not None:
            fn = [c for c in names if c in framed_art.index]
            fgot, _ = _portrait_step(lab, edge, top, s, framed_art, fn)
            if fgot is not None and fn:
                fhit, _fb = _pick(fgot[0], fgot[1], fgot[2], fn, framed_art, plate)
                if fhit is not None:
                    frame = "self"
                    got, hit, cand, used = fgot, fhit, fn, framed_art
        if hit is None and got is not None and len(names) < len(art.agents):
            wide, _ = _portrait_step(lab, edge, top, s, art, list(art.agents))
            if wide is not None:
                whit, _wb = _pick(wide[0], wide[1], wide[2], list(art.agents), art, plate)
                if whit is not None:
                    widened = f"side top {best:.3f}: none on plate at {PRESENT_Z}"
                    got, hit, cand = wide, whit, list(art.agents)
        if hit is None:
            ev = (_stop_evidence(got, names, art, lab, plate, edge, s.px(ICON_GAP_MIN))
                  if got is not None else {})
            # Absence read nearer the ROI's left edge than `EMPTY_VISIBLE_MIN`
            # is flagged as evidence; the count stands (see the constant).
            if not cut and edge < s.px(EMPTY_VISIBLE_MIN):
                ev["within_visible_min"] = round(float(edge), 2)
            if not cut and ev and ev.get("drawn_by"):
                # Drawn, but no agent's art clears the cut: present, unnamed.
                x = int(ev["x"])
                gap = edge - (x + art.w)
                row = {"k": k, "x": x, "y": int(ev["y"]), "gap": round(float(gap), 2),
                       "agent_at_best": None, "recognised": False,
                       "unrecognised_reason": UNRECOGNISED, "step_evidence": ev,
                       "plate_share": ev.get("plate_trans"),
                       "art_zncc": ev.get("art_zncc", {}), "art_candidates": "side",
                       "widened": None, "frame": None, "art_margin": art.margin,
                       "visible": round(min(1.0, (x + art.w) / art.w), 3),
                       "icon": gap >= s.px(ICON_GAP_MIN)}
                if row["icon"] and icon_temps:
                    iy = row["y"] + (art.h - s.px(ICON_PX)) / 2.0
                    row.update(read_icon(crop, x + art.w, iy, s, icon_temps, icons_admitted or []))
                out.append(row)
                edge = float(x)
                continue
            stop = {"reason": STOP_CUT if cut else STOP_ABSENT, "k": k,
                    "best_z": round(best, 4), **ev}
            break
        z, xs, ya = got
        ai, by, bx, zbest, share = hit
        per = z.reshape(-1, z.shape[2]).max(0)
        x = int(xs[bx])
        gap = edge - (x + used.w)
        y = int(ya + by)
        row = {"k": k, "x": x, "y": y, "gap": round(float(gap), 2),
               "agent_at_best": cand[ai], "recognised": True,
               "plate_share": None if share is None else round(share, 3),
               "art_zncc": {a: round(float(v), 4) for a, v in zip(cand, per)},
               "art_candidates": "all" if widened else "side", "widened": widened,
               "frame": frame, "art_margin": used.margin,
               "visible": round(min(1.0, (x + used.w) / used.w), 3),
               "icon": gap >= s.px(ICON_GAP_MIN),
               "step_evidence": _window_evidence(lab, plate, x, y, used, cand[ai])}
        if row["icon"] and icon_temps:
            iy = row["y"] + (used.h - s.px(ICON_PX)) / 2.0
            row.update(read_icon(crop, x + used.w, iy, s, icon_temps, icons_admitted or []))
        out.append(row)
        edge = float(x)
    count = None if stop["reason"] == STOP_CUT else len(out)
    return {"count": count, "count_min": len(out), "assisters": out, "stop": stop}


def view_anchors(row: dict) -> list[tuple[float, str]]:
    """The killfeed reader's priors for the killer art's left edge in one
    `killfeed_portrait` killer row, strongest first: the entry anchor, the
    plate's left end (`killfeed.KILLER_ART_FROM_PLATE`, scored at least
    `killfeed.PLATE_EDGE_MIN`), the art window. A prior within `EDGE_SEARCH`
    px of an earlier one is dropped."""
    out = []
    if row.get("entry_anchor") is not None:
        out.append((float(row["entry_anchor"]), "entry_anchor"))
    if row.get("plate_left") is not None and (row.get("plate_left_score") or 0) >= PLATE_EDGE_MIN:
        out.append((float(row["plate_left"]) + KILLER_ART_FROM_PLATE, "plate_left"))
    if row.get("art_x0") is not None and row.get("art_reason") is None:
        out.append((float(row["art_x0"]), "art_window"))
    kept = []
    for x, src in out:
        if all(abs(x - y) > EDGE_SEARCH for y, _ in kept):
            kept.append((x, src))
    return kept


def view_anchor(row: dict) -> tuple[float, str] | None:
    """The first of `view_anchors`, or None."""
    got = view_anchors(row)
    return got[0] if got else None


#: Anchor checks (`check_anchor`).
ANCHOR_VERIFIED = "verified"
ANCHOR_LOCAL = "local"
ANCHOR_ROWS = "all_rows"
ANCHOR_UNVERIFIED = "unverified"
ANCHOR_NO_KILLER = "no_killer"
#: Anchors the killer's art placed: a view reads its panel from these only.
ANCHOR_CHECKED = (ANCHOR_VERIFIED, ANCHOR_LOCAL, ANCHOR_ROWS)


def _killer_z(lab: np.ndarray, kart, killers: list[str], x_lo: int, x_hi: int, y_lo: int,
              y_hi: int):
    """The best correlation of any of `killers`' art with its left edge in
    [x_lo, x_hi] and top in [y_lo, y_hi] (ROI px): (z, x, y, agent), or None
    when no window lies wholly inside the crop."""
    h, w = lab.shape[:2]
    x_lo, y_lo = max(0, x_lo), max(0, y_lo)
    x_hi, y_hi = min(w - kart.w, x_hi), min(h - kart.h, y_hi)
    if x_hi < x_lo or y_hi < y_lo:
        return None
    best = None
    for y in range(y_lo, y_hi + 1):     # one row of windows at a time: bounded memory
        z = appearance.art_zncc(lab[y:y + kart.h, x_lo:x_hi + kart.w], kart, killers)[0]
        bx, ai = np.unravel_index(int(np.argmax(z)), z.shape)
        if best is None or z[bx, ai] > best[0]:
            best = (float(z[bx, ai]), x_lo + int(bx), y, killers[int(ai)])
    return best


def check_anchor(crop: np.ndarray, row: dict, s: KillfeedScale, kart,
                 killer: str | None, side: list[str] | None = None,
                 lab: np.ndarray | None = None) -> dict:
    """Where the killer's art starts in one view, checked against the
    killer's own art (`killer_art`). `killer` is the death verdict's killer
    agent (a prior from the death owner; the result `rests_on` it); where
    the verdict names none, `side` (the killer's side from the lineup) is the
    candidate set and `killer_at_best` names the agent whose art placed the
    edge. Each of the killfeed reader's priors (`view_anchors`) is scored
    within `killfeed.ART_PRIOR_X` columns and `ART_PRIOR_Y` rows; the best
    that reaches `killfeed.ART_SURPRISE_Z` is `verified`. Where none does,
    the search widens to the entry's band (every column, the prior's rows;
    then `killfeed.ART_WIDE_Y` rows either side about the column found, as
    the killfeed reader's own surprise search reaches) and
    a best at `ART_SURPRISE_Z` is `local`; else the first prior stands
    `unverified`. With neither a killer nor a side the priors stand
    unchecked (`no_killer`). `upstream_disagrees` says the chosen edge lies
    more than `EDGE_SEARCH` px from the reader's first prior, stored for the
    killfeed owner; the walk reads from `x`, `y`."""
    priors = view_anchors(row)
    top = row.get("art_y0")
    out = {"killer": killer, "killer_candidates": None, "killer_at_best": None,
           "priors": [{"prior": src, "x": round(x, 2)} for x, src in priors],
           "local": None, "rows": None, "status": None, "x": None, "y": top, "prior": None,
           "upstream_disagrees": None, "upstream_row_off": None}
    if not priors or top is None:
        out["status"] = REFUSE_NO_ANCHOR
        return out
    first_x, first_src = priors[0]
    killers = [k for k in ([killer] if killer else list(side or []))
               if kart is not None and k in kart.index]
    if not killers:
        out.update(status=ANCHOR_NO_KILLER, x=first_x, prior=first_src)
        return out
    out["killer_candidates"] = "verdict" if killer else "side"
    lab = appearance.to_lab(crop) if lab is None else lab
    px, py = s.n(ART_PRIOR_X), s.n(ART_PRIOR_Y)
    best = None
    for p, (x, src) in zip(out["priors"], priors):
        got = _killer_z(lab, kart, killers, int(round(x)) - px, int(round(x)) + px,
                        int(top) - py, int(top) + py)
        p["z"] = None if got is None else round(got[0], 4)
        if got is not None and got[0] >= ART_SURPRISE_Z and (best is None or got[0] > best[0]):
            best = (got[0], float(got[1]), int(got[2]), src, got[3])
    if best is not None and killer:
        out.update(status=ANCHOR_VERIFIED, x=best[1], y=best[2], prior=best[3],
                   killer_at_best=best[4])
    else:
        # A named killer's art the priors miss is a surprise. With only the
        # side known, a side agent's art can score at a prior inside another
        # agent's art (223d636bf8d2 1386.5 s: Skye 0.52 inside Reyna's), so the
        # band is always searched and its best stands.
        got = _killer_z(lab, kart, killers, 0, crop.shape[1], int(top) - py, int(top) + py)
        if got is not None and got[0] >= ART_SURPRISE_Z:
            # rows refined about the column found, as far as the killfeed
            # reader's own surprise search reaches (an entry still sliding in)
            wy = s.n(ART_WIDE_Y)
            fine = _killer_z(lab, kart, killers, got[1] - px, got[1] + px,
                             int(top) - wy, int(top) + wy)
            got = fine if fine is not None and fine[0] > got[0] else got
        if got is not None:
            out["local"] = {"x": got[1], "y": got[2], "z": round(got[0], 4), "agent": got[3]}
        near = got is not None and best is not None and abs(got[1] - best[1]) <= EDGE_SEARCH
        if got is not None and got[0] >= ART_SURPRISE_Z and near:
            out.update(status=ANCHOR_VERIFIED, x=float(got[1]), y=int(got[2]), prior=best[3],
                       killer_at_best=got[3])
        elif got is not None and got[0] >= ART_SURPRISE_Z:
            out.update(status=ANCHOR_LOCAL, x=float(got[1]), y=int(got[2]), prior="killer_art",
                       killer_at_best=got[3])
        else:
            # The band holds no killer art: the upstream row can be a whole
            # portrait off (c62c2b06bcfb 400.5 s: art_y0 0-2, Reyna at 15).
            # Search every row of the crop and keep the peak nearest the prior.
            rows = _killer_rows(lab, kart, killers, int(top))
            out["rows"] = rows
            if rows["pick"] is not None:
                p = rows["pick"]
                out.update(status=ANCHOR_ROWS, x=float(p["x"]), y=int(p["y"]), prior="killer_art",
                           killer_at_best=p["agent"])
            else:
                out.update(status=ANCHOR_UNVERIFIED, x=first_x, prior=first_src)
    out["upstream_disagrees"] = bool(abs(out["x"] - first_x) > EDGE_SEARCH)
    out["upstream_row_off"] = (int(out["y"]) - int(top)
                               if out["status"] in (ANCHOR_LOCAL, ANCHOR_ROWS) else None)
    out["x"] = round(float(out["x"]), 2)
    return out


#: The all-rows killer search (`_killer_rows`) screens the crop and the art
#: both shrunk by `ROWS_SHRINK` (`INTER_AREA`), keeping rows whose best
#: screened correlation reaches `ROWS_SCREEN_Z`, then scores each screened
#: peak at full size within `ROWS_REFINE` px; only the full-size score is cut
#: at `killfeed.ART_SURPRISE_Z`. The screen is chosen, not measured, below
#: that cut so a peak the shrink blurs is still refined.
ROWS_SHRINK = 2
ROWS_SCREEN_Z = 0.35
ROWS_REFINE = 3
#: A peak further than half the 39 px slot pitch [domain:killfeed/slot-pitch]
#: from the prior's row is another entry's killer and is never picked. On
#: the first 0.6.0 run, unbounded, 83 views took an all-rows peak at a
#: median 39 px (up to 179 px) from the prior: another entry with the same
#: killer, whose panel is not this death's. The review's five cases lie 3-15
#: px off.
ROWS_PICK_MAX = 19

_SHRUNK: dict = {}


def _shrunk_tiles(kart) -> "appearance.ArtTiles":
    """`kart` shrunk by `ROWS_SHRINK` (`INTER_AREA` on its Lab and alpha),
    cached per art set."""
    key = id(kart)
    if key not in _SHRUNK:
        f = ROWS_SHRINK
        h, w = max(4, kart.h // f), max(4, kart.w // f)
        lab = np.stack([cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA) for t in kart._lab])
        alpha = np.stack([cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)
                          for a in kart.alpha])
        _SHRUNK[key] = (kart, appearance.ArtTiles(kart.agents, lab, alpha,
                                                  max(0, kart.margin // f)))
    return _SHRUNK[key][1]


def _killer_rows(lab: np.ndarray, kart, killers: list[str], top: int) -> dict:
    """The killer's art over every row of the crop, for a view whose priors
    and band hold none (`check_anchor`, `ANCHOR_ROWS`). Every row is screened
    at `ROWS_SHRINK` (`ROWS_SCREEN_Z`); each run of screened rows is one
    peak, scored at full size about its best (`ROWS_REFINE`) and kept at
    `killfeed.ART_SURPRISE_Z`. The peak nearest the prior's row `top`, within
    `ROWS_PICK_MAX`, is picked (an entry above or below can hold the same
    killer), ties to the higher correlation. Returns {"peaks": [...], "pick":
    peak or None}."""
    h, w = lab.shape[:2]
    if h < kart.h or w < kart.w:
        return {"peaks": [], "pick": None}
    f = ROWS_SHRINK
    small = _shrunk_tiles(kart)
    lab_s = cv2.resize(lab, (w // f, h // f), interpolation=cv2.INTER_AREA)
    hs, ws = lab_s.shape[:2]
    hits = []
    for y in range(0, hs - small.h + 1):
        g = _killer_z(lab_s, small, killers, 0, ws, y, y)
        if g is not None and g[0] >= ROWS_SCREEN_Z:
            hits.append((y, g))
    runs, cur = [], []
    for y, g in hits:
        if cur and y - cur[-1][0] > 1:
            runs.append(cur)
            cur = []
        cur.append((y, g))
    if cur:
        runs.append(cur)
    peaks = []
    for run in runs:
        _y, g0 = max(run, key=lambda t: t[1][0])
        r = ROWS_REFINE
        g = _killer_z(lab, kart, killers, f * g0[1] - r, f * g0[1] + r,
                      f * g0[2] - r, f * g0[2] + r)
        if g is not None and g[0] >= ART_SURPRISE_Z:
            peaks.append({"x": int(g[1]), "y": int(g[2]), "z": round(float(g[0]), 4),
                          "agent": g[3], "screen_z": round(float(g0[0]), 4)})
    near = [p for p in peaks if abs(p["y"] - top) <= ROWS_PICK_MAX]
    pick = min(near, key=lambda p: (abs(p["y"] - top), -p["z"])) if near else None
    return {"peaks": peaks, "pick": pick}


def assist_observation(crop: np.ndarray, killer_row: dict, s: KillfeedScale, art,
                       candidates: list[str], icon_temps: dict | None,
                       icons_admitted: list[str], death_id: str | None = None,
                       killer: str | None = None, kart=None, framed_art=None,
                       side: list[str] | None = None) -> dict:
    """One `assist_observation` row for one view of an entry's killer: the
    panel read left of that killer's art (`check_anchor`, with `killer` or
    else `side`), or a refusal. `framed_art` is passed on the player's side
    (`read_panel`)."""
    base = {"kind": "assist_observation", "killfeed_assist_version": KILLFEED_ASSIST_VERSION,
            "t_ms": float(killer_row["t_ms"]), "frame_idx": killer_row.get("frame_idx"),
            "slot": killer_row.get("slot"), "entry": killer_row.get("entry"),
            "death_id": death_id, "killer_key": killer_row.get("observation_key"),
            "candidates": list(candidates)}
    lab = appearance.to_lab(crop)
    chk = check_anchor(crop, killer_row, s, kart, killer, side, lab)
    if chk["status"] == REFUSE_NO_ANCHOR or art is None:
        return {**base, "count": None, "count_min": 0, "assisters": [],
                "reason": REFUSE_NO_ANCHOR, "anchor_check": chk}
    checked = chk["status"] in ANCHOR_CHECKED
    # A checked edge is read alone; an unchecked one falls back through the
    # reader's priors while each reads no panel, as before the check.
    tries = ([(chk["x"], chk["prior"], chk["y"])] if checked
             else [(x, src, killer_row["art_y0"]) for x, src in view_anchors(killer_row)])
    tried = []
    for x, src, y in tries:
        got = read_panel(crop, x, float(y), s, art, candidates, icon_temps, icons_admitted,
                         framed_art, lab)
        tried.append({"prior": src, "x": round(x, 2), "count": got["count"]})
        if got["count"] != 0:
            break
    rests = [{"prior": src, "x": round(x, 2), "art_y0": y,
              "observation_key": killer_row.get("observation_key")}]
    if checked:
        rests.append({"death_killer": killer, "death_id": death_id} if killer
                     else {"lineup_side": list(side or [])})
        return {**base, **got, "reason": got["stop"]["reason"] if got["count"] is None else None,
                "rests_on": rests, "priors_tried": tried, "anchor_check": chk}
    # No killer art confirms the edge: whatever the walk read from it is kept
    # as evidence, never as a count or an assister (a panel walked from the
    # wrong place reads absence it never saw).
    why = REFUSE_UNCHECKED if chk["status"] == ANCHOR_NO_KILLER else REFUSE_UNVERIFIED
    return {**base, "count": None, "count_min": 0, "assisters": [], "stop": {"reason": why},
            "reason": why, "unverified_read": {"count": got["count"],
                                               "count_min": got["count_min"],
                                               "stop": got["stop"],
                                               "agents": [a["agent_at_best"]
                                                          for a in got["assisters"]]},
            "rests_on": rests, "priors_tried": tried, "anchor_check": chk}
