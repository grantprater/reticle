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

# The icon's white mask and its normalised grid are measurements, so the reader
# layer owns them; this module names what they describe.
from ..killfeed import ICON_GRID, icon_grid, icon_white_mask
from .killfeed_kits import kill_kits, open_questions

# 0.5.0 (2026-09-25): `entry_weapon` takes the match's agents and drops ability
# exemplars no agent there can cast; `ability_agent` names an ability's caster.
# 0.6.0 (2026-10-01): a refusal says why. An icon scoring under the floor
# against every allowed name is `new`; one whose best name clears the floor
# but not the runner-up's margin is `ambiguous` (they were `no_close_exemplar`
# and `tie`). An entry too thinly named takes the reason most of its frames
# gave, and stores every frame's reason (`frame_reasons`).
# 0.7.0 (2026-10-01): context narrows the candidates by role, in tiers. Given
# the acting role's agent (`actor`: the killer of a kill or a second-life
# death, the reviver of a revive), a frame is first named against the guns and
# that agent's own abilities, where an ability-shaped name of the kit needs
# only NAME_KIT_MIN_IOU; then against the match's agents; then, when nothing
# allowed clears the floor, against the full gallery, the surprise path. The
# answer says what it `rests_on`, and a fixed one entry in AUDIT_EVERY also
# stores the full search apart (`audit`).
# 0.8.0 (2026-10-01): an icon whose caster is the revived, not the acting
# role (`REVIVED_CASTER_ICONS`: KAY/O's NULL/cmd in a revive entry), makes no
# caster claim on the actor.
# 0.9.0 (2026-10-01): the kit floor lowers only for an agent whose every
# killfeed-capable ability a fact lists (`KILLFEED_KITS`) and the gallery
# holds; no fact lists a whole kit, so no agent's floor lowers yet.
# 1.0.0 (2026-10-01): `KILLFEED_KITS` comes from `adjudication.killfeed_kits`,
# the player's rule [domain:killfeed/damaging-ability-kill-icon] applied to the
# reference's descriptions. An agent with an ability the rule leaves undecided
# (`KILLFEED_OPEN`) keeps NAME_MIN_IOU, and the lowered floor covers only the
# listed abilities.
# 1.1.0 (2026-10-01): the kits take the player's answers (killfeed-kits-0.3.0),
# so no agent holds an open question and Sage and Clove qualify.
# 1.2.0 (2026-10-01): ABILITY_CANONICAL_NAMES follows the reference's slots
# (Brimstone, Deadlock, Harbor and Phoenix had two slots swapped; six agents
# were missing), so `ability_agent` and the reference-asset matcher name
# those abilities and agents correctly; it reads weapon-gallery-0.5.0.
WEAPON_ADJUDICATION_VERSION = "weapon-adjudication-1.2.0"

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
        # [domain:weapons/warden]: new in 2026-10, a long-range rifle; its
        # exemplars entered weapon-gallery-0.4.0 [domain:killfeed/warden-icon].
        "Warden",
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

#: Typical aspect ratio ranges (width / height) by weapon class. No caller
#: reads them, and they describe no measured icon: every gun name in
#: weapon-gallery-0.3.0 has its exemplars' white-mask aspect outside its
#: class's range (Vandal 3.30-3.62 against the rifle's 1.8-2.9). The gate
#: that bounds an icon's aspect is NAME_ASPECT_TOL against each name's own
#: exemplars; `NAME_ASPECTS` holds a name the gallery may lack.
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

#: Reference ability asset stem (`<Agent>_<slot>`) to in-game ability name, as
#: `<store>/reference/abilities.json` (valorant-api) names each slot; the
#: casing is ours. Before 2026-10-01 four agents had slots swapped here:
#: Phoenix's Ability1 read Curveball, so the labeller showed the Hot Hands
#: art [domain:killfeed/phoenix-hot-hands-icon] captioned "Curveball"
#: [domain:abilities/phoenix-slots]. `tests/test_ability_names.py` checks the
#: table against the reference.
ABILITY_CANONICAL_NAMES = {
    # Astra
    "Astra_Ability1": "Nova Pulse",
    "Astra_Ability2": "Nebula / Dissipate",
    "Astra_Grenade": "Gravity Well",
    "Astra_Ultimate": "Astral Form / Cosmic Divide",
    # Breach
    "Breach_Ability1": "Flashpoint",
    "Breach_Ability2": "Fault Line",
    "Breach_Grenade": "Aftershock",
    "Breach_Ultimate": "Rolling Thunder",
    # Brimstone
    "Brimstone_Ability1": "Incendiary",
    "Brimstone_Ability2": "Sky Smoke",
    "Brimstone_Grenade": "Stim Beacon",
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
    "Deadlock_Ability2": "GravNet",
    "Deadlock_Grenade": "Barrier Mesh",
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
    "Harbor_Ability1": "High Tide",
    "Harbor_Ability2": "Cove",
    "Harbor_Grenade": "Storm Surge",
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
    # Miks
    "Miks_Ability1": "Harmonize",
    "Miks_Ability2": "Waveform",
    "Miks_Grenade": "M-pulse",
    "Miks_Ultimate": "Bassquake",
    # Omen
    "Omen_Ability1": "Paranoia",
    "Omen_Ability2": "Dark Cover",
    "Omen_Grenade": "Shrouded Step",
    "Omen_Ultimate": "From the Shadows",
    # Phoenix
    "Phoenix_Ability1": "Hot Hands",
    "Phoenix_Ability2": "Curveball",
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
    # Tejo
    "Tejo_Ability1": "Special Delivery",
    "Tejo_Ability2": "Guided Salvo",
    "Tejo_Grenade": "Stealth Drone",
    "Tejo_Ultimate": "Armageddon",
    # Veto
    "Veto_Ability1": "Chokehold",
    "Veto_Ability2": "Interceptor",
    "Veto_Grenade": "Crosscut",
    "Veto_Ultimate": "Evolution",
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
    # Waylay
    "Waylay_Ability1": "Lightspeed",
    "Waylay_Ability2": "Refract",
    "Waylay_Grenade": "Saturate",
    "Waylay_Ultimate": "Convergent Paths",
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

    white = icon_white_mask(crop)
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
#: Built by `prototypes/weapon_icons.py gallery` from `<store>/labels/weapon_icon/`
#: and the per-entry names in `<store>/labels/killfeed_icon/`; it carries its own
#: provenance. 0.2.0 splits the group the player named only "Ability" into the
#: abilities they named per entry, the revive icons among them. 0.3.0 adds
#: the Blade Storm knife [domain:killfeed/jett-blade-storm-icon] once the
#: locator boxed it, and Curveball and Annihilation. 0.4.0 adds the members
#: the player named in groups of icons the owner refused as new
#: (`labels/killfeed_new_icon/`): the Warden [domain:killfeed/warden-icon] and
#: KAY/O's NULL/cmd in a revive entry's weapon slot
#: [domain:killfeed/kayo-downed-entry]; a member whose aspect lies beyond
#: NAME_ASPECT_TOL of its name's (`weapon_icons.new_icon_entries`) is a crop
#: fault and stays out. 0.5.0 names a per-entry ability row by the ability
#: stem the player picked, through the corrected ABILITY_CANONICAL_NAMES: the
#: b3b9defb6fd7 1731.5 s exemplar, which 0.4.0 held as Curveball, is Hot Hands
#: [domain:killfeed/phoenix-hot-hands-icon]. 0.6.0 rebinds the per-entry
#: names to the `killfeed_weapon` rows killfeed-weapon-0.7.0 reread from the
#: crop cache (corpus rerun, 2026-10-01); the labels are unchanged.
WEAPON_GALLERY_VERSION = "weapon-gallery-0.6.0"
NAME_MIN_IOU = 0.75           # a name needs an exemplar at least this close
NAME_MARGIN = 0.05            # and must clear the best exemplar of any other name
NAME_ASPECT_TOL = 0.12        # |log| aspect difference beyond which two icons never match

#: Why `name_icon` refuses. `new`: no allowed name scores NAME_MIN_IOU, so the
#: icon may be one the gallery lacks (a new gun such as the Warden
#: [domain:killfeed/warden-icon], or a known icon drawn badly). `ambiguous`: a
#: known name clears the floor but another lies within NAME_MARGIN of it. The
#: two call for different remedies: a new icon for a label, an ambiguous one
#: for context.
REFUSE_NEW = "new"
REFUSE_AMBIGUOUS = "ambiguous"

#: The white-mask aspect of a name the gallery may lack, from its fact: the
#: reference a new exemplar of that name is checked against when the gallery
#: holds none. The Warden draws 85-86 px on the 34 px band, aspect about 3.86
#: [domain:killfeed/warden-icon].
NAME_ASPECTS = {"Warden": 3.86}

#: The floor for an ability-shaped name of the acting agent's own kit. With
#: the candidates narrowed to one agent's few abilities, the floor guards
#: against an icon of another kit, not against the whole gallery: no gallery
#: ability icon scores above
#: [metric:killfeed_openset/kit_null@weapon-gallery-0.3.0#null_max_ability=0.513]
#: against another agent's abilities (`prototypes/killfeed_openset.py kitnull`).
#: A gun-shaped ability (Headhunter, Tour De Force, Boom Bot; exemplar aspect
#: over ABILITY_MAX_ASPECT) keeps NAME_MIN_IOU, since a Sheriff scores up to
#: [metric:killfeed_openset/kit_null@weapon-gallery-0.3.0#null_max_gun_shaped=0.82]
#: against Headhunter [domain:killfeed/chamber-gun-shaped-abilities]. The
#: null samples other agents' icons, not an agent's own unlabelled abilities,
#: so the floor lowers only where the gallery holds the agent's whole
#: killfeed kit (`KILLFEED_KITS`): an unlisted ability of the actor's would
#: otherwise be named as the nearest listed one.
NAME_KIT_MIN_IOU = 0.52

#: Every ability of an agent that can draw a killfeed weapon-slot icon: its
#: damaging abilities [domain:killfeed/damaging-ability-kill-icon] and the icons
#: a killfeed fact names, as `adjudication.killfeed_kits` derives them.
#: `KILLFEED_OPEN` holds, per agent, the abilities that rule cannot decide; the
#: questions are in docs/ABILITY_MECHANICS_SHEET.md, "Killfeed icons".
KILLFEED_KITS: dict[str, frozenset] = kill_kits()
KILLFEED_OPEN: dict[str, frozenset] = open_questions()

#: The audit of the narrowing: an entry whose key hashes to 0 modulo this also
#: gets the full search, stored apart (`audit`) and never counted a surprise.
AUDIT_EVERY = 10

#: Player names in the mined gallery that are not guns, by what they are.
#: Chamber's Headhunter and Tour De Force draw gun silhouettes
#: [domain:killfeed/chamber-gun-shaped-abilities]; "Ability" is a group the
#: player named only as an ability, left to the ability gallery to name. Not
#: Dead Yet and Resurrection mark revive entries [domain:killfeed/revive-entries].
#: Phoenix's Hot Hands draws rising flames, Blaze a four-segment wall and
#: Curveball radiating light [domain:killfeed/phoenix-blaze-icon]
#: [domain:killfeed/phoenix-curveball-icon], by the player's confirmed reading
#: [domain:killfeed/phoenix-flame-icons-reading].
MINED_NOT_GUN = {"Melee": "melee", "Environmental": "environmental", "Other": "other",
                 "Ability": "ability", "Headhunter": "ability", "Tour De Force": "ability",
                 "Aftershock": "ability", "Orbital Strike": "ability", "Boom Bot": "ability",
                 "Not Dead Yet": "ability", "Resurrection": "ability",
                 "Blade Storm": "ability", "Curveball": "ability", "Hot Hands": "ability",
                 "Annihilation": "ability",
                 "Clove expiry": "ability", "NULL/cmd": "ability"}

#: Icons whose caster is the revived, not the acting role. A KAY/O revive
#: entry draws NULL/cmd's icon in the weapon slot with any teammate as the
#: reviver [domain:killfeed/kayo-downed-entry], so the icon names the revived
#: KAY/O and says nothing of the left name.
REVIVED_CASTER_ICONS = frozenset({"NULL/cmd"})


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


#: The self entries that are an agent's own ability but not one of its four
#: official icons [domain:rounds/clove-revive-expiry-entry].
EXTRA_ABILITY_AGENTS = {"Clove expiry": "Clove"}


def ability_agent(name: Optional[str]) -> Optional[str]:
    """The agent whose ability `name` is, from `ABILITY_CANONICAL_NAMES` (its
    asset stem is `<Agent>_<slot>`), or None for a gun or an unknown name."""
    if name in EXTRA_ABILITY_AGENTS:
        return EXTRA_ABILITY_AGENTS[name]
    for stem, n in ABILITY_CANONICAL_NAMES.items():
        if n == name:
            return stem.rsplit("_", 1)[0]
    return None


def caster_claim(entity_id: str, name: Optional[str],
                 rests_on: Optional[list] = None) -> Optional[dict]:
    """An identity claim that the ability `name` was cast by its agent, for the
    killer entity `entity_id`; None for a gun or a name with no caster. The
    icon is other pixels than the killer's portrait, so the claim is a witness
    the arbiter can weigh against it; the name is decided there.

    `rests_on` is the answer's own (`entry_weapon`). A name the actor's kit
    shaped took its candidates from the acting entity's verdict, so the claim
    `depends_on` that entity and is never counted as an independent witness
    of it: the prior is weighed once. An icon in REVIVED_CASTER_ICONS names
    the revived, not the actor, so it makes no claim."""
    from .identity import identity_claim
    agent = ability_agent(name)
    if agent is None or name in REVIVED_CASTER_ICONS:
        return None
    on = sorted({r["entity_id"] for r in rests_on or ()
                 if r.get("context") == "actor" and r.get("entity_id")})
    return identity_claim(entity_id, agent, channel="killfeed_weapon",
                          source_version=WEAPON_ADJUDICATION_VERSION, depends_on=on or None,
                          evidence={"ability": name, "gallery": WEAPON_GALLERY_VERSION,
                                    "rests_on": [r.get("context") for r in rests_on or ()]})


def restrict_gallery(gallery: dict, agents) -> tuple[dict, list[str]]:
    """The gallery without ability exemplars no agent in `agents` can cast,
    and the names it dropped. Guns and unattributed names stay."""
    agents = set(agents)
    drop = sorted({str(n) for n in gallery["names"]
                   if ability_agent(str(n)) is not None and ability_agent(str(n)) not in agents})
    keep = np.array([str(n) not in drop for n in gallery["names"]])
    return {k: (v[keep] if isinstance(v, np.ndarray) and len(v) == len(keep) else v)
            for k, v in gallery.items()}, drop


def name_icon(grid: np.ndarray, aspect: float, gallery: dict) -> dict:
    """Nearest exemplar per name; a name only when it clears every other by a margin."""
    return _name_icon(grid, aspect, _icon_index(gallery))


def _icon_index(gallery: dict) -> dict:
    """What `name_icon` reads of a gallery, prepared once for many icons:
    the exemplar masks as float rows with their sums, and each name's
    exemplars grouped, names in first-appearance order."""
    g = gallery["masks"].reshape(len(gallery["masks"]), -1).astype(np.float32)
    names = [str(n) for n in gallery["names"]]
    order = list(dict.fromkeys(names))
    rows = {n: [] for n in order}
    for k, n in enumerate(names):
        rows[n].append(k)
    perm = [k for n in order for k in rows[n]]
    starts = np.cumsum([0] + [len(rows[n]) for n in order[:-1]])
    return {"g": g, "g_sum": g.sum(1), "aspects": gallery["aspects"], "names": order,
            "perm": np.array(perm, dtype=np.intp), "starts": starts.astype(np.intp)}


def _name_icon(grid: np.ndarray, aspect: float, index: dict,
               kit: frozenset = frozenset()) -> dict:
    """The nearest exemplar per name. A name must clear its floor
    (NAME_KIT_MIN_IOU for a name in `kit`, NAME_MIN_IOU otherwise) and beat
    every other name by NAME_MARGIN: `new` when no name clears its floor,
    `ambiguous` when the best name that does lacks the margin."""
    g = index["g"]
    q = grid.reshape(-1).astype(np.float32)
    inter = g @ q
    iou = inter / np.maximum(index["g_sum"] + q.sum() - inter, 1)
    iou[np.abs(np.log(index["aspects"] / aspect)) > NAME_ASPECT_TOL] = 0.0
    # Each name's best exemplar; scores are never negative, so this is the
    # running maximum from 0.0 over that name's exemplars.
    tops = (np.maximum.reduceat(iou[index["perm"]], index["starts"]).tolist()
            if index["names"] else [])
    best: dict[str, float] = {n: max(0.0, v) for n, v in zip(index["names"], tops)}
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    top, score = ranked[0]
    margin = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
    out = {"best": top, "score": round(score, 3), "margin": round(margin, 3),
           "scores": dict(ranked[:5])}
    cleared = [n for n, v in ranked if v >= (NAME_KIT_MIN_IOU if n in kit else NAME_MIN_IOU)]
    if not cleared:
        return dict(out, name=None, reason=REFUSE_NEW)
    if cleared[0] != top or margin < NAME_MARGIN:
        # A kit name that cleared its lower floor under a name that did not
        # clear its own is as unresolved as a thin margin.
        return dict(out, name=None, reason=REFUSE_AMBIGUOUS)
    return dict(out, name=top)


def _gun_class(name: str) -> Optional[str]:
    for w_c, w_list in WEAPON_TAXONOMY.items():
        if name in w_list:
            return w_c
    return None


ENTRY_MIN_NAMED = 2           # frames that must name the entry's icon
ENTRY_MIN_SHARE = 0.8         # of those, the share the top name must hold
ENTRY_BOX_TOL = 2             # px an entry's icon box width may vary over its life


def bind_entry(entry: dict, observations: list[dict]) -> list[dict]:
    """The stored `killfeed_weapon` rows that belong to one killfeed entry.

    `entry` is a `session_entries` row (`t_first`, `t_last`, `slot`, `sig`);
    `observations` are stored `killfeed_weapon` rows. The divider column is the
    icon's LEFT edge in a right-aligned row, so it depends on the victim's name
    as well as the icon, and two adjacent entries with different guns can share
    it (a Spectre and a Vandal at 1906.5 s on a06f04a0059f). So the entry is
    followed frame by frame instead: it starts in the slot it appeared in, only
    ever rises one slot as an older entry expires, and takes at most one row per
    frame, its own slot before the one above.
    """
    from ..checks import KF_SIG_TOL

    sig = entry.get("sig")
    by_frame: dict[float, dict[int, dict]] = {}
    for o in observations:
        if (o.get("kind") == "weapon_icon_observation" and o.get("grid")
                and entry["t_first"] <= o["t_ms"] <= entry["t_last"]
                and (sig is None or abs(o["wx0"] - sig) <= KF_SIG_TOL)):
            by_frame.setdefault(o["t_ms"], {})[o["slot"]] = o
    bound, slot, width = [], entry["slot"], None
    for t in sorted(by_frame):
        # The whole stack rises at once, so the entry below can arrive in the
        # slot this one just left; the icon's box width, fixed for an entry's
        # life, tells them apart where the column cannot.
        here = {s: o for s, o in by_frame[t].items()
                if width is None or abs((o["wx1"] - o["wx0"]) - width) <= ENTRY_BOX_TOL}
        for s in (slot, slot - 1):
            if s in here:
                slot = s
                bound.append(here[s])
                if width is None:
                    width = here[s]["wx1"] - here[s]["wx0"]
                break
    return bound


def _thin_reason(reasons: dict[str, int], n_bound: int) -> str:
    """Why a thinly named entry refuses: `new` or `ambiguous` when more than
    half its frames refused for that reason, else `too_few_named` (a short
    entry whose few frames did name it)."""
    for why in (REFUSE_NEW, REFUSE_AMBIGUOUS):
        if 2 * reasons.get(why, 0) > n_bound:
            return why
    return "too_few_named"


def kit_names(gallery: dict, agent: Optional[str]) -> frozenset:
    """The names that take NAME_KIT_MIN_IOU in `agent`'s kit tier: its listed
    `ability_shaped_names`, but only when `KILLFEED_KITS` lists the agent,
    `KILLFEED_OPEN` holds no question of it, and `gallery` holds every name
    listed; otherwise none, and the floor stays NAME_MIN_IOU."""
    listed = KILLFEED_KITS.get(agent or "")
    if (not listed or KILLFEED_OPEN.get(agent or "")
            or not listed <= {str(n) for n in gallery["names"]}):
        return frozenset()
    return ability_shaped_names(gallery, agent) & listed


def ability_shaped_names(gallery: dict, agent: Optional[str]) -> frozenset:
    """The ability-shaped names of `agent`'s kit in `gallery`: the names
    `ability_agent` gives to the agent whose exemplars' median aspect is at
    most ABILITY_MAX_ASPECT."""
    if not agent:
        return frozenset()
    names = np.array([str(n) for n in gallery["names"]])
    return frozenset(n for n in set(names.tolist()) if ability_agent(n) == agent
                     and float(np.median(gallery["aspects"][names == n])) <= ABILITY_MAX_ASPECT)


def candidate_tiers(gallery: dict, agents=None, actor: Optional[dict] = None) -> list[dict]:
    """The candidate sets `entry_weapon` tries, narrowest first: `kit` (the
    guns and unattributed names, with only `actor`'s own abilities), `lineup`
    (with the abilities of `agents`, the match's lineup) and `full`. A tier is
    present only when its context is given; `full` always is."""
    out = []
    agent = (actor or {}).get("agent")
    if agent:
        g, dropped = restrict_gallery(gallery, {agent})
        out.append({"tier": "kit", "index": _icon_index(g), "kit": kit_names(g, agent),
                    "dropped": dropped})
    if agents:
        g, dropped = restrict_gallery(gallery, agents)
        out.append({"tier": "lineup", "index": _icon_index(g), "kit": frozenset(),
                    "dropped": dropped})
    out.append({"tier": "full", "index": _icon_index(gallery), "kit": frozenset(),
                "dropped": []})
    return out


def name_frame(grid: np.ndarray, aspect: float, tiers: list[dict]) -> dict:
    """One icon named through `candidate_tiers`: the first tier where some
    allowed name clears its floor decides (a name, or `ambiguous`, which a
    wider set cannot cure); an icon no tier names is `new` at the widest."""
    for t in tiers:
        v = _name_icon(grid, aspect, t["index"], t["kit"])
        if v.get("reason") != REFUSE_NEW:
            return dict(v, tier=t["tier"])
    return dict(v, tier=tiers[-1]["tier"])


def _count(frames: list[dict], allowed: set) -> dict:
    """An entry's verdict from its frames, counting only names reached at the
    tiers in `allowed`; a frame named at another tier counts as new."""
    names: dict[str, int] = {}
    reasons: dict[str, int] = {}
    tiers: dict[str, dict[str, int]] = {}
    for f in frames:
        if f["name"] is not None and f["tier"] in allowed:
            names[f["name"]] = names.get(f["name"], 0) + 1
            per = tiers.setdefault(f["name"], {})
            per[f["tier"]] = per.get(f["tier"], 0) + 1
        else:
            why = f.get("reason") or REFUSE_NEW
            reasons[why] = reasons.get(why, 0) + 1
    out = {"named": sum(names.values()), "names": names, "frame_reasons": reasons,
           "status": "refused", "name": None}
    if out["named"] < ENTRY_MIN_NAMED:
        return dict(out, reason=_thin_reason(reasons, len(frames)))
    top = max(names, key=names.get)
    if names[top] < ENTRY_MIN_SHARE * out["named"]:
        return dict(out, reason="frames_disagree")
    return dict(out, status="resolved", reason=None, name=top, tiers=tiers[top])


def _decide(frames: list[dict], narrow: set) -> dict:
    """Narrow first: the entry from the names its context (`narrow`, the
    tiers below `full` that were tried) gave its frames. Only when those
    leave it `new` do the full gallery's names count, and an answer reached
    that way is a `surprise`. Names the surprise path gave frames of an entry
    the context decided are kept apart (`surprise_frames`), never counted."""
    if not narrow:
        return dict(_count(frames, {"full"}), surprise=False)
    v = _count(frames, narrow)
    extra: dict[str, int] = {}
    for f in frames:
        if f["name"] is not None and f["tier"] == "full":
            extra[f["name"]] = extra.get(f["name"], 0) + 1
    if v["status"] != "resolved" and v["reason"] == REFUSE_NEW and extra:
        w = _count(frames, narrow | {"full"})
        if w["status"] == "resolved":
            return dict(w, surprise=True, surprise_frames=extra)
    return dict(v, surprise=False, **({"surprise_frames": extra} if extra else {}))


def audit_entry(key: Optional[str]) -> bool:
    """Whether the entry keyed `key` (its `death_key`) is in the audit sample:
    the first eight hex digits of its SHA-1, read as a number, are 0 modulo
    AUDIT_EVERY. The rule is fixed in advance and reads nothing the entry's
    answer depends on."""
    import hashlib
    return key is not None and int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % AUDIT_EVERY == 0


def entry_weapon(entry: dict, observations: list[dict],
                 gallery: Optional[dict] = None, agents=None,
                 actor: Optional[dict] = None, key: Optional[str] = None,
                 frames: bool = False) -> dict:
    """The weapon or ability behind one killfeed entry, from stored descriptors.

    The entry's rows are those `bind_entry` follows. One frame is not an
    answer: the entry is named only when ENTRY_MIN_NAMED frames name it and
    the top name holds ENTRY_MIN_SHARE of them. A refusal keeps its cause:
    `new` or `ambiguous` when most frames refused that way (`_thin_reason`),
    `too_few_named` or `frames_disagree` otherwise, with every frame's reason
    in `frame_reasons`.

    Context narrows first (`candidate_tiers`, `name_frame`, `_decide`).
    `actor` is the acting role's agent as `adjudication.death.entry_actor`
    gives it from witnesses other than this icon: `{"agent", "entity_id",
    "role", "channels"}`. `agents`, the match's lineup (both sides), drops the
    abilities no one there can cast; the names dropped are kept
    (`restricted_to_lineup`). An entry its context leaves `new` widens to the
    full gallery, and a name found only there is a `surprise`.

    The answer says what it `rests_on`: the actor when the answer without
    the actor's kit differs (the kit shaped it), the lineup when names from
    the lineup's set decided it, nothing for a surprise or with no context.
    A caster claim from an answer resting on the actor depends on the
    actor's entity (`caster_claim`).

    `key`, the entry's `death_key`, puts one entry in AUDIT_EVERY into the
    audit (`audit_entry`): the full search's answer is stored apart in
    `audit`. `kit_floor_frames` counts the frames only the kit's lower floor
    named; each rests on the actor. `frames=True` adds each bound row's own
    answer (`frames`), with its `rests_on`.
    """
    from ..killfeed import unpack_icon_grid

    out = {"version": WEAPON_ADJUDICATION_VERSION, "gallery": WEAPON_GALLERY_VERSION,
           "name": None, "category": None, "status": "refused"}
    if gallery is None:
        gallery = load_mined_gallery()
    if gallery is None:
        return dict(out, reason="no_gallery")
    tiers = candidate_tiers(gallery, agents, actor)
    by = {t["tier"]: t for t in tiers}
    if "lineup" in by:
        out["restricted_to_lineup"] = by["lineup"]["dropped"]
    if "kit" in by:
        out["actor"] = {k: actor.get(k) for k in ("agent", "entity_id", "role", "channels")}
    bound = bind_entry(entry, observations)
    out["observations"] = len(bound)
    if not bound:
        return dict(out, named=0, names={}, frame_reasons={}, reason="no_observation",
                    rests_on=[], surprise=False)
    grids = [(unpack_icon_grid(o["grid"]), o["aspect"]) for o in bound]
    narrow = set(by) - {"full"}
    rows = [name_frame(g, a, tiers) for g, a in grids]
    v = _decide(rows, narrow)
    rests_on: list[dict] = []
    if v["status"] == "resolved" and not v["surprise"]:
        kit_shaped = False
        if "kit" in by:
            plain = [t for t in tiers if t["tier"] != "kit"]
            w = _decide([name_frame(g, a, plain) for g, a in grids], narrow - {"kit"})
            kit_shaped = (w["status"], w["name"]) != (v["status"], v["name"])
        if kit_shaped:
            rests_on.append({"context": "actor", **out["actor"]})
        if "lineup" in by and (not kit_shaped or v["tiers"].get("lineup")):
            rests_on.append({"context": "lineup"})
    out.update({k: v[k] for k in ("named", "names", "frame_reasons")})
    # A frame its kit's lower floor named rests on the actor even when the
    # entry's name stands without it (`kit_floor_frames`).
    on_kit = [r["name"] is not None and r["tier"] == "kit" and r["score"] < NAME_MIN_IOU
              for r in rows]
    out.update(rests_on=rests_on, surprise=v["surprise"], kit_floor_frames=sum(on_kit))
    if v.get("surprise_frames"):
        out["surprise_frames"] = v["surprise_frames"]
    if v["status"] == "resolved":
        out["tiers"] = v["tiers"]
    if audit_entry(key):
        full = [by["full"]]
        a = _count([name_frame(g, x, full) for g, x in grids], {"full"})
        out["audit"] = {"rule": f"sha1(death_key)[:8] % {AUDIT_EVERY} == 0",
                        "status": a["status"], "name": a["name"], "reason": a["reason"],
                        "names": a["names"],
                        "agrees": (a["status"], a["name"]) == (v["status"], v["name"])}
    if frames:
        out["frames"] = [{"t_ms": o["t_ms"], "slot": o["slot"], "name": r["name"],
                          "reason": r.get("reason"), "tier": r["tier"], "best": r["best"],
                          "score": r["score"], "margin": r["margin"],
                          "rests_on": [{"context": "actor", **out["actor"]}] if k else []}
                         for o, r, k in zip(bound, rows, on_kit)]
    if v["status"] != "resolved":
        return dict(out, reason=v["reason"])
    top = v["name"]
    category = MINED_NOT_GUN.get(top, "gun")
    return dict(out, status="resolved", reason=None, category=category,
                name=None if top == "Ability" else top)


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
