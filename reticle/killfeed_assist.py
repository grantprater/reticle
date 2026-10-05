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
from the killer art's left edge (the row's entry anchor, else its art window)
leftwards, one assister at a time, never over the whole row. Each step scores
the side's portrait art (`appearance.art_zncc`, the art shrunk to the brush's
36 x 18 with `INTER_AREA`) at every column where the assister's right edge can
sit: against the panel's right end with no icon, or one icon cell (16 px)
further left. The best placement says whether an icon cell lies between the
portrait and the panel's right end; the next assister ends where this one
begins.

**Absence is a reading.** Where no candidate's art correlates at
`PRESENT_Z` the step reads "no assister": the panel holds `count` assisters. Before
reading absence the step widens to every agent with art (the surprise path):
a portrait that only an agent outside the side matches is stored as present
with `widened`, and its agent stays for the arbiter to refuse. A step whose
search the ROI's left edge cuts stops with `count` None and `count_min`.

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

**Measured** (`prototypes/assist_panel_eval.py`, 21 matches, 3 views per
entry, against Riot's assist credit on paired deaths). Where the count is
read, the panel's presence agrees with Riot's assisted kill at precision
[metric:assist_panel/riot#presence_precision=0.9958] and recall
[metric:assist_panel/riot#presence_recall=0.9572]; a named assister is one
Riot credits at [metric:assist_panel/riot#assister_precision=0.996]. Every
Astra assist is missed: her art scores under `PRESENT_Z` at this size. The
ROI's left edge cuts the panel of a long killer name; those deaths keep a
lower bound ([metric:assist_panel/riot#lower_bound=257] deaths, each one Riot
credits).

Game art is loaded from the store's game-file reference (`ICON_BUILD`), never
copied into this repository; the portrait art is the killfeed owner's
(`appearance.killfeed_art`).

Owns [owns:killfeed-assist-panel].
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

import cv2

from . import appearance
from .killfeed import (KILLER_ART_FROM_PLATE, PLATE_EDGE_MIN,
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
KILLFEED_ASSIST_VERSION = "killfeed-assist-0.4.0"

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

# Where an assister's right edge sits, relative to the right end it abuts
# (the killer art's left edge, or the previous assister's left edge). On 81
# labelled assisted entries the portrait's right edge sat -1 px (0 to -2)
# from the killer art's left edge with no icon, -16 to -17 with one.
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
#: 1 of 55 false. Riot's records are the held-out check.
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
#: chosen, not measured, and Riot's records check it.
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


def _display_name(path: Path) -> str | None:
    if not path.is_file():
        return None
    for obj in json.loads(path.read_text(encoding="utf-8")):
        name = ((obj.get("Properties") or {}).get("DisplayName") or {}).get("LocalizedString")
        if name:
            return name
    return None


@lru_cache(maxsize=4)
def icon_art(store_root: str) -> tuple[dict, dict]:
    """({name: path}, provenance) of every icon the panel can draw: each
    ability UIData's `DisplayIcon` the build's `killfeed-icons` export holds,
    named `<Agent>/<ability>` (the agent's own UIData `DisplayName`, KAY/O
    spelt KAY_O as the lineup spells it; the ability's UIData `DisplayName`),
    and `GENERIC_ICONS`. Empty when the store holds no export."""
    d = icon_build_dir(store_root)
    man = d / "killfeed-icons" / "manifest.jsonl"
    if not man.is_file():
        return {}, {"build": ICON_BUILD, "reason": "no_game_icons"}
    chars = d / "ability-data" / "ShooterGame" / "Content" / "Characters"
    out, missing = {}, []
    for line in man.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sel = row.get("selected_by") or ""
        if "/UIData_" not in sel or row.get("status") != "ok":
            continue
        game = sel.split(":", 1)[1]                    # ShooterGame/Content/...uasset
        code = game.split("/Characters/", 1)[1].split("/", 1)[0]
        agent = _display_name(chars / code / f"{code}_UIData.json")
        ability = _display_name(d / "ability-data" / game.replace(".uasset", ".json"))
        png = d / row["output"]
        if not agent or not ability or not png.is_file():
            missing.append(game)
            continue
        out[f"{agent.replace('/', '_')}/{ability}"] = png
    for name, rel in GENERIC_ICONS.items():
        png = d / _KILLCALLOUT / rel
        if png.is_file():
            out[name] = png
        else:
            missing.append(rel)
    return out, {"build": ICON_BUILD, "icons": len(out), "missing": missing}


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


def portrait_art(art_dir, s: KillfeedScale) -> "appearance.ArtTiles | None":
    """The killfeed portrait art at the assist brush's size, in Lab."""
    return appearance.killfeed_art(art_dir, s.n(PORTRAIT_H), s.n(PORTRAIT_W), s.n(ART_MARGIN))


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


def read_panel(crop: np.ndarray, right: float, top: float, s: KillfeedScale, art,
               candidates: list[str], icon_temps: dict | None = None,
               icons_admitted: list[str] | None = None) -> dict:
    """Read the panel left of a killer art whose left edge is `right` and
    top `top` (ROI px). `candidates` are the agents the caller admits (the
    killer's side); the full art set is the surprise path. A portrait is
    present where its art correlation reaches `PRESENT_Z` and the art's
    transparent pixels show the plate (`killfeed.plate_score`, share at
    least `PLATE_SHARE_MIN`): the assist portrait is drawn on the killer's
    plate colour, the world behind the feed is not. Returns `count` (None
    with `count_min` where the ROI cuts the search), `assisters` (beside the
    killer first) and `stop` (why the walk ended)."""
    lab = appearance.to_lab(crop)
    plate = plate_score(crop)
    names = [c for c in candidates if c in art.index] or list(art.agents)
    out, edge = [], float(right)
    stop = {"reason": STOP_FULL}
    for k in range(MAX_ASSISTERS):
        got, cut = _portrait_step(lab, edge, top, s, art, names)
        widened, cand, hit, best = None, names, None, -1.0
        if got is not None:
            hit, best = _pick(got[0], got[1], got[2], names, art, plate)
        if hit is None and got is not None and len(names) < len(art.agents):
            wide, _ = _portrait_step(lab, edge, top, s, art, list(art.agents))
            if wide is not None:
                whit, _wb = _pick(wide[0], wide[1], wide[2], list(art.agents), art, plate)
                if whit is not None:
                    widened = f"side top {best:.3f}: none on plate at {PRESENT_Z}"
                    got, hit, cand = wide, whit, list(art.agents)
        if hit is None:
            stop = {"reason": STOP_CUT if cut else STOP_ABSENT, "k": k,
                    "best_z": round(best, 4)}
            break
        z, xs, ya = got
        ai, by, bx, zbest, share = hit
        per = z.reshape(-1, z.shape[2]).max(0)
        x = int(xs[bx])
        gap = edge - (x + art.w)
        row = {"k": k, "x": x, "y": int(ya + by), "gap": round(float(gap), 2),
               "agent_at_best": cand[ai],
               "plate_share": None if share is None else round(share, 3),
               "art_zncc": {a: round(float(v), 4) for a, v in zip(cand, per)},
               "art_candidates": "all" if widened else "side", "widened": widened,
               "visible": round(min(1.0, (x + art.w) / art.w), 3),
               "icon": gap >= s.px(ICON_GAP_MIN)}
        if row["icon"] and icon_temps:
            iy = row["y"] + (art.h - s.px(ICON_PX)) / 2.0
            row.update(read_icon(crop, x + art.w, iy, s, icon_temps, icons_admitted or []))
        out.append(row)
        edge = float(x)
    count = None if stop["reason"] == STOP_CUT else len(out)
    return {"count": count, "count_min": len(out), "assisters": out, "stop": stop}


def view_anchors(row: dict) -> list[tuple[float, str]]:
    """The killer art's left edge for one `killfeed_portrait` killer row, by
    prior, strongest first: the entry anchor, the plate's left end
    (`killfeed.KILLER_ART_FROM_PLATE`, scored at least
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


def assist_observation(crop: np.ndarray, killer_row: dict, s: KillfeedScale, art,
                       candidates: list[str], icon_temps: dict | None,
                       icons_admitted: list[str], death_id: str | None = None) -> dict:
    """One `assist_observation` row for one view of an entry's killer: the
    panel read left of that killer's art, or a refusal."""
    base = {"kind": "assist_observation", "killfeed_assist_version": KILLFEED_ASSIST_VERSION,
            "t_ms": float(killer_row["t_ms"]), "frame_idx": killer_row.get("frame_idx"),
            "slot": killer_row.get("slot"), "entry": killer_row.get("entry"),
            "death_id": death_id, "killer_key": killer_row.get("observation_key"),
            "candidates": list(candidates)}
    anchors = view_anchors(killer_row)
    if not anchors or killer_row.get("art_y0") is None or art is None:
        return {**base, "count": None, "count_min": 0, "assisters": [],
                "reason": REFUSE_NO_ANCHOR}
    tried = []
    for x, src in anchors:
        got = read_panel(crop, x, float(killer_row["art_y0"]), s, art, candidates,
                         icon_temps, icons_admitted)
        tried.append({"prior": src, "x": round(x, 2), "count": got["count"]})
        if got["count"] != 0:
            break
    return {**base, **got, "reason": got["stop"]["reason"] if got["count"] is None else None,
            "rests_on": [{"prior": src, "x": round(x, 2), "art_y0": killer_row["art_y0"],
                          "observation_key": killer_row.get("observation_key")}],
            "priors_tried": tried}
