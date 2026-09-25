"""Adjudication of killfeed weapon and ability icons.

Extracts, normalizes, and classifies weapon silhouettes and ability icons
from killfeed divider bounding boxes (wx0..wx1, y0..y1).

Differentiates:
1. Guns (sidearms, smgs, shotguns, rifles, snipers, machine guns, melee);
2. Agent lethal abilities (e.g. Breach Aftershock, Raze Showstopper, Sova Shock Bolt);
3. Environmental death icons (e.g. falling off Abyss).

Owns [owns:killfeed-weapon].
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

WEAPON_ADJUDICATION_VERSION = "weapon-adjudication-0.3.0"

#: White mask cut for killfeed line art against colored plate backgrounds.
#: The icon is drawn at V >= 240 and S < 20; the translucent green plate over a
#: bright scene reaches S 50-75 at V 185-200, and the old cut (185, 75) admitted
#: it, inflating the tight box and splitting one Vandal into three groups on
#: a06f04a0059f (prototypes/weapon_icons.py).
ICON_WHITE_V_MIN = 220
ICON_WHITE_S_MAX = 45

#: Aspect ratio and width thresholds separating abilities from guns.
ABILITY_MAX_WIDTH_PX = 36
ABILITY_MAX_ASPECT = 1.35

#: Weapon classification taxonomy by category and canonical in-game names.
WEAPON_TAXONOMY = {
    "sidearm": [
        "Classic",
        "Shorty",
        "Frenzy",
        "Ghost",
        "Bandit",
        "Sheriff",
    ],
    "smg": [
        "Stinger",
        "Spectre",
    ],
    "shotgun": [
        "Bucky",
        "Judge",
    ],
    "rifle": [
        "Bulldog",
        "Guardian",
        "Phantom",
        "Vandal",
    ],
    "sniper": [
        "Marshal",
        "Outlaw",
        "Operator",
    ],
    "machine_gun": [
        "Ares",
        "Odin",
    ],
    "melee": [
        "Tactical Knife",
    ],
    "environmental": [
        "Fall",
    ],
}

#: Typical aspect ratio ranges (width / height) by weapon class.
CLASS_ASPECT_RANGES = {
    "ability": (0.4, 1.25),
    "sidearm": (1.1, 1.9),
    "smg": (1.7, 2.3),
    "shotgun": (2.2, 3.2),
    "rifle": (1.8, 2.9),
    "sniper": (2.8, 4.5),
    "machine_gun": (2.4, 3.5),
    "melee": (1.5, 2.8),
}

#: Canonical mapping from reference ability asset stem to in-game ability name.
ABILITY_CANONICAL_NAMES = {
    # Breach
    "Breach_Ability1": "Flashpoint",
    "Breach_Ability2": "Fault Line",
    "Breach_Grenade": "Aftershock",
    "Breach_Ultimate": "Rolling Thunder",
    # Brimstone
    "Brimstone_Ability1": "Incendiary",
    "Brimstone_Ability2": "Stim Beacon",
    "Brimstone_Grenade": "Sky Smoke",
    "Brimstone_Ultimate": "Orbital Strike",
    # Chamber
    "Chamber_Ability1": "Headhunter",
    "Chamber_Ability2": "Rendezvous",
    "Chamber_Grenade": "Trademark",
    "Chamber_Ultimate": "Tour De Force",
    # Clove
    "Clove_Ability1": "Meddle",
    "Clove_Ability2": "Ruse",
    "Clove_Grenade": "Pick-Me-Up",
    "Clove_Ultimate": "Not Dead Yet",
    # Cypher
    "Cypher_Ability1": "Cyber Cage",
    "Cypher_Ability2": "Spycam",
    "Cypher_Grenade": "Trapwire",
    "Cypher_Ultimate": "Neural Theft",
    # Deadlock
    "Deadlock_Ability1": "Sonic Sensor",
    "Deadlock_Ability2": "Barrier Mesh",
    "Deadlock_Grenade": "GravNet",
    "Deadlock_Ultimate": "Annihilation",
    # Fade
    "Fade_Ability1": "Seize",
    "Fade_Ability2": "Haunt",
    "Fade_Grenade": "Prowler",
    "Fade_Ultimate": "Nightfall",
    # Gekko
    "Gekko_Ability1": "Wingman",
    "Gekko_Ability2": "Dizzy",
    "Gekko_Grenade": "Mosh Pit",
    "Gekko_Ultimate": "Thrash",
    # Harbor
    "Harbor_Ability1": "Cove",
    "Harbor_Ability2": "High Tide",
    "Harbor_Grenade": "Cascade",
    "Harbor_Ultimate": "Reckoning",
    # Iso
    "Iso_Ability1": "Undercut",
    "Iso_Ability2": "Double Tap",
    "Iso_Grenade": "Contingency",
    "Iso_Ultimate": "Kill Contract",
    # Jett
    "Jett_Ability1": "Updraft",
    "Jett_Ability2": "Tailwind",
    "Jett_Grenade": "Cloudburst",
    "Jett_Ultimate": "Blade Storm",
    # KAY/O
    "KAY_O_Ability1": "FLASH/drive",
    "KAY_O_Ability2": "ZERO/point",
    "KAY_O_Grenade": "FRAG/ment",
    "KAY_O_Ultimate": "NULL/cmd",
    # Killjoy
    "Killjoy_Ability1": "Alarmbot",
    "Killjoy_Ability2": "Turret",
    "Killjoy_Grenade": "Nanoswarm",
    "Killjoy_Ultimate": "Lockdown",
    # Neon
    "Neon_Ability1": "Relay Bolt",
    "Neon_Ability2": "High Gear",
    "Neon_Grenade": "Fast Lane",
    "Neon_Ultimate": "Overdrive",
    # Phoenix
    "Phoenix_Ability1": "Curveball",
    "Phoenix_Ability2": "Hot Hands",
    "Phoenix_Grenade": "Blaze",
    "Phoenix_Ultimate": "Run It Back",
    # Raze
    "Raze_Ability1": "Blast Pack",
    "Raze_Ability2": "Paint Shells",
    "Raze_Grenade": "Boom Bot",
    "Raze_Ultimate": "Showstopper",
    # Reyna
    "Reyna_Ability1": "Devour",
    "Reyna_Ability2": "Dismiss",
    "Reyna_Grenade": "Leer",
    "Reyna_Ultimate": "Empress",
    # Sage
    "Sage_Ability1": "Slow Orb",
    "Sage_Ability2": "Healing Orb",
    "Sage_Grenade": "Barrier Orb",
    "Sage_Ultimate": "Resurrection",
    # Skye
    "Skye_Ability1": "Trailblazer",
    "Skye_Ability2": "Guiding Light",
    "Skye_Grenade": "Regrowth",
    "Skye_Ultimate": "Seekers",
    # Sova
    "Sova_Ability1": "Shock Bolt",
    "Sova_Ability2": "Recon Bolt",
    "Sova_Grenade": "Owl Drone",
    "Sova_Ultimate": "Hunter's Fury",
    # Viper
    "Viper_Ability1": "Poison Cloud",
    "Viper_Ability2": "Toxic Screen",
    "Viper_Grenade": "Snake Bite",
    "Viper_Ultimate": "Viper's Pit",
    # Vyse
    "Vyse_Ability1": "Shear",
    "Vyse_Ability2": "Arc Rose",
    "Vyse_Grenade": "Razorvine",
    "Vyse_Ultimate": "Steel Garden",
    # Yoru
    "Yoru_Ability1": "Blindside",
    "Yoru_Ability2": "Gatecrash",
    "Yoru_Grenade": "Fakeout",
    "Yoru_Ultimate": "Dimensional Drift",
}


@dataclass(frozen=True)
class IconObservation:
    """An extracted and pre-processed killfeed divider icon crop."""

    crop: np.ndarray
    white_mask: np.ndarray
    width: int
    height: int
    aspect_ratio: float
    fill_ratio: float
    is_ability_candidate: bool
    is_weapon_candidate: bool
    bbox: Optional[tuple[int, int, int, int]] = None  # (wx0, wx1, y0, y1)


@dataclass(frozen=True)
class WeaponVerdict:
    """Adjudicated classification for a killfeed divider icon."""

    name: Optional[str]
    category: str  # "gun" | "ability" | "environmental"
    weapon_class: str  # "rifle" | "sidearm" | "sniper" | "smg" | "shotgun" | "machine_gun" | "melee" | "ability" | "environmental"
    confidence: float = 0.0
    margin: float = 0.0
    status: str = "abstained"  # "resolved" | "abstained"
    scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "weapon_class": self.weapon_class,
            "confidence": self.confidence,
            "margin": self.margin,
            "status": self.status,
            "scores": self.scores,
            "metadata": self.metadata,
            "adjudication_version": WEAPON_ADJUDICATION_VERSION,
        }


def extract_icon_observation(
    frame_or_crop: np.ndarray,
    bbox: Optional[tuple[int, int, int, int]] = None,
) -> IconObservation:
    """Extract and normalize white line-art icon observation.

    If bbox is provided as (wx0, wx1, y0, y1), crops from frame_or_crop.
    Otherwise, assumes frame_or_crop is already the localized icon crop.
    """
    if bbox is not None:
        wx0, wx1, y0, y1 = bbox
        crop = frame_or_crop[y0:y1, wx0:wx1]
    else:
        crop = frame_or_crop

    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        empty = np.zeros((1, 1), dtype=bool)
        return IconObservation(
            crop=crop,
            white_mask=empty,
            width=0,
            height=0,
            aspect_ratio=0.0,
            fill_ratio=0.0,
            is_ability_candidate=False,
            is_weapon_candidate=False,
            bbox=bbox,
        )

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 2] > ICON_WHITE_V_MIN) & (hsv[:, :, 1] < ICON_WHITE_S_MAX)

    # Reject boundary line bleeds from adjacent killfeed slots
    if h >= 25 and white.any():
        num_labels, labels_im, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8))
        if num_labels > 2:
            max_area = stats[1:, cv2.CC_STAT_AREA].max()
            clean_white = np.zeros_like(white)
            for label_idx in range(1, num_labels):
                comp_y = stats[label_idx, cv2.CC_STAT_TOP]
                comp_h = stats[label_idx, cv2.CC_STAT_HEIGHT]
                comp_area = stats[label_idx, cv2.CC_STAT_AREA]
                if (comp_y <= 1 or (comp_y + comp_h >= h - 1)) and comp_h <= 3 and comp_area < max_area * 0.4:
                    continue
                clean_white[labels_im == label_idx] = True
            if clean_white.any():
                white = clean_white

    aspect = float(w) / float(h) if h > 0 else 0.0
    fill = float(white.sum()) / float(w * h) if (w * h) > 0 else 0.0

    is_ability = (w <= ABILITY_MAX_WIDTH_PX) and (aspect <= ABILITY_MAX_ASPECT)
    is_weapon = not is_ability and (w > 15)

    return IconObservation(
        crop=crop,
        white_mask=white,
        width=w,
        height=h,
        aspect_ratio=round(aspect, 2),
        fill_ratio=round(fill, 3),
        is_ability_candidate=is_ability,
        is_weapon_candidate=is_weapon,
        bbox=bbox,
    )


_ABILITY_GALLERY_CACHE: dict[str, np.ndarray] = {}


def load_ability_gallery(assets_dir: Optional[Path | str] = None) -> dict[str, np.ndarray]:
    """Load and cache transparent reference ability PNGs from reference store."""
    global _ABILITY_GALLERY_CACHE
    if _ABILITY_GALLERY_CACHE:
        return _ABILITY_GALLERY_CACHE

    if assets_dir is None:
        from ..store import Store
        try:
            assets_dir = Store().root / "reference" / "assets" / "abilities"
        except Exception:
            assets_dir = Path("reticle-store/reference/assets/abilities")
    else:
        assets_dir = Path(assets_dir)

    if not assets_dir.is_dir():
        return {}

    loaded = {}
    for p in assets_dir.glob("*.png"):
        raw = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if raw is not None and len(raw.shape) == 3 and raw.shape[2] == 4:
            alpha = raw[:, :, 3]
            ys, xs = np.where(alpha > 128)
            if len(ys) > 10:
                raw = raw[int(ys.min()):int(ys.max()+1), int(xs.min()):int(xs.max()+1)]
            loaded[p.stem] = raw

    _ABILITY_GALLERY_CACHE = loaded
    return _ABILITY_GALLERY_CACHE


_WEAPON_GALLERY_CACHE: dict[str, np.ndarray] = {}


def load_weapon_gallery(assets_dir: Optional[Path | str] = None) -> dict[str, np.ndarray]:
    """Load and cache canonical reference weapon PNGs from reference store."""
    global _WEAPON_GALLERY_CACHE
    if _WEAPON_GALLERY_CACHE:
        return _WEAPON_GALLERY_CACHE

    if assets_dir is None:
        from ..store import Store
        try:
            assets_dir = Store().root / "reference" / "assets" / "weapons"
        except Exception:
            assets_dir = Path("reticle-store/reference/assets/weapons")
    else:
        assets_dir = Path(assets_dir)

    if not assets_dir.is_dir():
        return {}

    loaded = {}
    for p in assets_dir.glob("*.png"):
        raw = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if raw is not None and len(raw.shape) == 3 and raw.shape[2] == 4:
            loaded[p.stem] = raw

    _WEAPON_GALLERY_CACHE = loaded
    return _WEAPON_GALLERY_CACHE


def estimate_weapon_class(width: int, aspect_ratio: float) -> str:
    """Heuristically estimate weapon class from bounding box width and aspect ratio."""
    if width <= ABILITY_MAX_WIDTH_PX and aspect_ratio <= ABILITY_MAX_ASPECT:
        return "ability"
    if width < 45 or aspect_ratio < 1.7:
        return "sidearm"
    if width < 58 or aspect_ratio < 2.0:
        return "smg"
    if width < 85 or aspect_ratio < 2.8:
        return "rifle"
    if width >= 85 or aspect_ratio >= 2.8:
        return "sniper"
    return "gun"


#: The mined gallery: exemplar icons named by the player, one file per version.
#: Built by `prototypes/weapon_icons.py gallery` from `<store>/labels/weapon_icon/`;
#: it carries its own provenance. Held out on five sessions it named
#: [metric:weapon_icons/gallery-heldout@corpus#seen_correct=29] player-seen icons, all
#: correctly, and refused one.
WEAPON_GALLERY_VERSION = "weapon-gallery-0.1.0"
ICON_GRID = (16, 64)          # h, w of a tight icon mask resized to one height
ICON_MIN_TIGHT_W = 12         # narrower than any gun or ability icon
NAME_MIN_IOU = 0.75           # a name needs an exemplar at least this close
NAME_MARGIN = 0.05            # and must clear the best exemplar of any other name
NAME_ASPECT_TOL = 0.12        # |log| aspect difference beyond which two icons never match

#: Player names in the mined gallery that are not guns, by what they are.
#: Chamber's Headhunter and Tour De Force draw gun silhouettes
#: [domain:killfeed/chamber-gun-shaped-abilities]; "Ability" is a group the
#: player named only as an ability, left to the ability gallery to name.
MINED_NOT_GUN = {"Melee": "melee", "Environmental": "environmental", "Other": "other",
                 "Ability": "ability", "Headhunter": "ability", "Tour De Force": "ability"}


def icon_grid(white_mask: np.ndarray) -> Optional[tuple[np.ndarray, float]]:
    """A white mask cut to its tight box and resized to ICON_GRID, with its aspect."""
    ys, xs = np.nonzero(white_mask)
    if len(xs) < 10 or xs.max() - xs.min() + 1 < ICON_MIN_TIGHT_W:
        return None
    tight = white_mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    grid = cv2.resize(tight.astype(np.uint8), ICON_GRID[::-1], interpolation=cv2.INTER_AREA)
    return grid, tight.shape[1] / tight.shape[0]


_MINED_CACHE: dict[str, dict] = {}


def mined_gallery_path(store_root: Optional[Path] = None) -> Path:
    if store_root is None:
        from ..store import Store
        store_root = Store().root
    return Path(store_root) / "reference" / "weapon_gallery" / f"{WEAPON_GALLERY_VERSION}.npz"


def load_mined_gallery(path: Optional[Path | str] = None) -> Optional[dict]:
    """The mined, player-named exemplar gallery, or None when it is not built."""
    path = Path(path) if path is not None else mined_gallery_path()
    key = str(path)
    if key not in _MINED_CACHE:
        if not path.is_file():
            return None
        z = np.load(path)
        _MINED_CACHE[key] = {k: z[k] for k in ("names", "masks", "aspects")}
    return _MINED_CACHE[key]


def name_icon(grid: np.ndarray, aspect: float, gallery: dict) -> dict:
    """Nearest exemplar per name; a name only when it clears every other by a margin."""
    g = gallery["masks"].reshape(len(gallery["masks"]), -1).astype(np.float32)
    q = grid.reshape(-1).astype(np.float32)
    inter = g @ q
    iou = inter / np.maximum(g.sum(1) + q.sum() - inter, 1)
    iou[np.abs(np.log(gallery["aspects"] / aspect)) > NAME_ASPECT_TOL] = 0.0
    best: dict[str, float] = {}
    for n, v in zip(gallery["names"], iou):
        best[str(n)] = max(best.get(str(n), 0.0), float(v))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    top, score = ranked[0]
    margin = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
    out = {"best": top, "score": round(score, 3), "margin": round(margin, 3),
           "scores": dict(ranked[:5])}
    if score < NAME_MIN_IOU:
        return dict(out, name=None, reason="no_close_exemplar")
    if margin < NAME_MARGIN:
        return dict(out, name=None, reason="tie")
    return dict(out, name=top)


def _gun_class(name: str) -> Optional[str]:
    for w_c, w_list in WEAPON_TAXONOMY.items():
        if name in w_list:
            return w_c
    return None


def classify_killfeed_icon(
    obs_or_crop: IconObservation | np.ndarray,
    active_agent: Optional[str] = None,
    gallery: Optional[dict[str, np.ndarray]] = None,
    weapon_gallery: Optional[dict[str, np.ndarray]] = None,
    min_score: float = 0.60,
    min_margin: float = 0.10,
    mined_gallery: Optional[dict] = None,
    use_mined: bool = True,
) -> WeaponVerdict:
    """Classify a killfeed divider icon against ability and weapon reference galleries.

    The mined gallery answers first when it is built: a gun, melee, an
    environmental death or a named gun-shaped ability. An icon it knows only as
    "Ability", or refuses, falls through to the ability gallery for squarish
    icons and the reference templates for the rest. When `active_agent` is
    provided (e.g. Breach or Raze), candidate ability templates for that agent
    are prioritized.
    """
    if isinstance(obs_or_crop, np.ndarray):
        obs = extract_icon_observation(obs_or_crop)
    else:
        obs = obs_or_crop

    if obs.width == 0 or obs.height == 0:
        return WeaponVerdict(
            name=None,
            category="gun",
            weapon_class="gun",
            status="abstained",
            metadata={"reason": "empty_crop"},
        )

    # 0. The mined gallery, named by the player.
    mined = None
    if use_mined:
        if mined_gallery is None:
            mined_gallery = load_mined_gallery()
        cut = icon_grid(obs.white_mask) if mined_gallery is not None else None
        if cut is not None:
            mined = name_icon(cut[0], cut[1], mined_gallery)
            n = mined["name"]
            if n is not None and n != "Ability":
                category = MINED_NOT_GUN.get(n, "gun")
                return WeaponVerdict(
                    name=n,
                    category=category,
                    weapon_class=_gun_class(n) or category,
                    confidence=mined["score"],
                    margin=mined["margin"],
                    status="resolved",
                    scores=mined["scores"],
                    metadata={"source": WEAPON_GALLERY_VERSION,
                              "width": obs.width, "aspect_ratio": obs.aspect_ratio},
                )

    # 1. Check ability match if candidate or squarish dimensions
    if obs.is_ability_candidate or (obs.width <= 36 and obs.aspect_ratio <= 1.35):
        if gallery is None:
            gallery = load_ability_gallery()

        if gallery:
            # Filter candidate gallery by active_agent if provided
            if active_agent:
                cands = {k: v for k, v in gallery.items() if k.lower().startswith(active_agent.lower())}
                if not cands:
                    cands = gallery
            else:
                cands = gallery

            # Extract tight foreground bounding box of white mask
            ys, xs = np.where(obs.white_mask)
            if len(ys) > 8:
                tight_white = obs.white_mask[int(ys.min()):int(ys.max()+1), int(xs.min()):int(xs.max()+1)].astype(np.float32)
            else:
                tight_white = obs.white_mask.astype(np.float32)

            th_obs, tw_obs = tight_white.shape
            scores: dict[str, float] = {}
            for stem, raw in cands.items():
                tys, txs = np.where(raw[:, :, 3] > 128)
                if len(tys) > 8:
                    raw_tight = raw[int(tys.min()):int(tys.max()+1), int(txs.min()):int(txs.max()+1)]
                else:
                    raw_tight = raw

                best = 0.0
                for dy in (-3, -2, -1, 0, 1, 2, 3):
                    th = th_obs + dy
                    if th <= 0:
                        continue
                    tw = int(round(raw_tight.shape[1] * (th / raw_tight.shape[0])))
                    if tw <= 0:
                        continue
                    resized = cv2.resize(raw_tight, (tw, th))
                    mask = (resized[:, :, 3] > 128).astype(np.float32)
                    if tight_white.shape[0] >= mask.shape[0] and tight_white.shape[1] >= mask.shape[1]:
                        res = cv2.matchTemplate(tight_white, mask, cv2.TM_CCOEFF_NORMED)
                        _, max_v, _, _ = cv2.minMaxLoc(res)
                        if not math.isnan(max_v) and max_v > best:
                            best = float(max_v)
                    elif mask.shape[0] >= tight_white.shape[0] and mask.shape[1] >= tight_white.shape[1]:
                        res = cv2.matchTemplate(mask, tight_white, cv2.TM_CCOEFF_NORMED)
                        _, max_v, _, _ = cv2.minMaxLoc(res)
                        if not math.isnan(max_v) and max_v > best:
                            best = float(max_v)
                if best > 0.0:
                    scores[stem] = round(best, 3)

            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            if sorted_scores:
                top_stem, top_score = sorted_scores[0]
                runner_up = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
                margin = round(top_score - runner_up, 3)
                canonical_name = ABILITY_CANONICAL_NAMES.get(top_stem, top_stem)

                if top_score >= min_score and margin >= min_margin:
                    return WeaponVerdict(
                        name=canonical_name,
                        category="ability",
                        weapon_class="ability",
                        confidence=top_score,
                        margin=margin,
                        status="resolved",
                        scores=dict(sorted_scores[:5]),
                        metadata={
                            "asset_stem": top_stem,
                            "aspect_ratio": obs.aspect_ratio,
                            "width": obs.width,
                        },
                    )

    # 2. Template matching for weapons
    if weapon_gallery is None:
        weapon_gallery = load_weapon_gallery()

    if weapon_gallery and obs.width >= 20:
        ys, xs = np.where(obs.white_mask)
        if len(ys) > 10:
            tight_white = obs.white_mask[int(ys.min()):int(ys.max()+1), int(xs.min()):int(xs.max()+1)].astype(np.float32)
        else:
            tight_white = obs.white_mask.astype(np.float32)

        th_obs, tw_obs = tight_white.shape
        aspect_obs = float(tw_obs) / float(th_obs) if th_obs > 0 else 0.0

        w_scores: dict[str, float] = {}
        for w_name, raw in weapon_gallery.items():
            tmpl_mask = (raw[:, :, 3] > 128).astype(np.float32)
            tys, txs = np.where(tmpl_mask > 0)
            if len(tys) > 5:
                tmpl_mask = tmpl_mask[int(tys.min()):int(tys.max()+1), int(txs.min()):int(txs.max()+1)]
            th_tmpl, tw_tmpl = tmpl_mask.shape
            aspect_tmpl = float(tw_tmpl) / float(th_tmpl) if th_tmpl > 0 else 0.0

            # Aspect ratio gate
            if abs(aspect_tmpl - aspect_obs) > 1.2:
                continue

            best = 0.0
            for dy in (-2, -1, 0, 1, 2):
                th = th_obs + dy
                if th <= 0:
                    continue
                tw = int(round(tw_tmpl * (th / float(th_tmpl))))
                if tw <= 0:
                    continue
                resized = cv2.resize(tmpl_mask, (tw, th))
                if tight_white.shape[0] >= resized.shape[0] and tight_white.shape[1] >= resized.shape[1]:
                    res = cv2.matchTemplate(tight_white, resized, cv2.TM_CCOEFF_NORMED)
                    _, max_v, _, _ = cv2.minMaxLoc(res)
                    if not math.isnan(max_v) and max_v > best:
                        best = float(max_v)
                elif resized.shape[0] >= tight_white.shape[0] and resized.shape[1] >= tight_white.shape[1]:
                    res = cv2.matchTemplate(resized, tight_white, cv2.TM_CCOEFF_NORMED)
                    _, max_v, _, _ = cv2.minMaxLoc(res)
                    if not math.isnan(max_v) and max_v > best:
                        best = float(max_v)
            if best > 0.0:
                w_scores[w_name] = round(best, 3)

        sorted_w = sorted(w_scores.items(), key=lambda x: x[1], reverse=True)
        if sorted_w:
            top_w, top_score = sorted_w[0]
            runner_up = sorted_w[1][1] if len(sorted_w) > 1 else 0.0
            margin = round(top_score - runner_up, 3)
            # Find weapon class in taxonomy
            w_class = estimate_weapon_class(obs.width, obs.aspect_ratio)
            for w_c, w_list in WEAPON_TAXONOMY.items():
                if top_w in w_list:
                    w_class = w_c
                    break

            if top_score >= 0.70 and margin >= 0.04:
                return WeaponVerdict(
                    name=top_w,
                    category="gun",
                    weapon_class=w_class,
                    confidence=top_score,
                    margin=margin,
                    status="resolved",
                    scores=dict(sorted_w[:5]),
                    metadata={
                        "aspect_ratio": obs.aspect_ratio,
                        "width": obs.width,
                        "height": obs.height,
                    },
                )

    # 3. The mined gallery knew it for an ability the ability gallery cannot name.
    if mined is not None and mined["name"] == "Ability":
        return WeaponVerdict(
            name=None,
            category="ability",
            weapon_class="ability",
            confidence=mined["score"],
            margin=mined["margin"],
            status="abstained",
            scores=mined["scores"],
            metadata={"reason": "unnamed_ability", "source": WEAPON_GALLERY_VERSION},
        )

    # 4. Geometric class estimation fallback for guns
    predicted_class = estimate_weapon_class(obs.width, obs.aspect_ratio)
    return WeaponVerdict(
        name=None,  # Specific weapon gun model requires template match
        category="gun",
        weapon_class=predicted_class,
        confidence=round(min(1.0, obs.fill_ratio * 2.0), 2),
        margin=0.0,
        status="abstained",
        metadata={
            "width": obs.width,
            "height": obs.height,
            "aspect_ratio": obs.aspect_ratio,
            "fill_ratio": obs.fill_ratio,
        },
    )
