"""Source profiles: the routing key for extraction (design doc SS3, stage 00).

A profile names a HUD layout. Regions of interest are stored as *fractions* of
frame width/height so one profile covers every resolution at a given aspect
ratio.

VALORANT_16_9 was measured against real 1920x1080 footage on 2026-08-23
("2026-08-23 18-24-15.mp4", Abyss). Run `reticle probe <video>` after any HUD
restyle or layout-setting change -- it renders the boxes onto sample frames so
you can see what each ROI actually lands on, then edit the numbers here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Roi:
    """A region of interest in fractional coordinates (0..1 of frame size)."""

    name: str
    x0: float
    y0: float
    x1: float
    y1: float

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Resolve to integer pixel bounds, clamped to the frame."""
        px0 = max(0, min(width - 1, int(round(self.x0 * width))))
        py0 = max(0, min(height - 1, int(round(self.y0 * height))))
        px1 = max(px0 + 1, min(width, int(round(self.x1 * width))))
        py1 = max(py0 + 1, min(height, int(round(self.y1 * height))))
        return px0, py0, px1, py1


@dataclass(frozen=True)
class OverlayZone:
    """A region where a toggled on-screen readout can appear.

    Valorant's performance stats are optional and come in three display modes --
    text, graph, or both -- with text laid along the top edge and graphs stacked
    down the right. Which ones are enabled is the player's choice, and they
    *flow*: turning one off shifts the rest rather than leaving a hole. That
    rules out cataloguing individual readouts by position.

    What is stable is the envelope. Each zone below is the extent measured with
    every readout switched on, so any subset fits inside it. That makes the zone
    a usable static fact even though the contents are not: it says which ROIs
    are at risk, and bounds where a per-capture occlusion mask needs to look.

    Measured at 1080p from "2026-08-23 22-17-12.mp4" (practice range, all
    readouts on, display mode "both").
    """

    name: str
    x0: float
    y0: float
    x1: float
    y1: float

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        return (
            int(round(self.x0 * width)), int(round(self.y0 * height)),
            int(round(self.x1 * width)), int(round(self.y1 * height)),
        )

    def hits(self, roi: "Roi") -> bool:
        """True if this zone overlaps the ROI, in fractional coordinates."""
        return not (
            self.x1 <= roi.x0 or self.x0 >= roi.x1
            or self.y1 <= roi.y0 or self.y0 >= roi.y1
        )


PERF_OVERLAY_ZONES = [
    # Text mode: a single ribbon along the very top, growing rightward as more
    # readouts are enabled. Ends at y 0.016 against the topmost ROI edge at
    # 0.020 -- five pixels of clearance at 1080p, which is worth re-checking
    # after any HUD scale change.
    OverlayZone("perf_text", 0.000, 0.000, 1.000, 0.018),
    # Graph mode: a two-column stack down the right. Overlaps the lower half of
    # the killfeed, which costs entry slots 3-5; the three most recent entries
    # sit above it and stay readable.
    OverlayZone("perf_graphs", 0.730, 0.200, 1.000, 0.745),
]


@dataclass(frozen=True)
class MinimapMode:
    """Valorant minimap settings that change what the minimap ROI contains.

    These are a routing key, not cosmetics. They decide two things:

      * how much signal `minimap_dchange` carries. Fixed + uncentered means the
        map only changes when player dots move, so the signal falls to zero in
        buy and post-round -- which is the dominant misclassification in the
        rule-based baseline. Rotating or centered means the whole map moves
        every frame, so dchange is high almost continuously and stops
        discriminating "round live" from "alive and turning".
      * whether a constant minimap-pixel -> world homography exists at all,
        which stage 03 position tracking needs. Only fixed + always_same +
        uncentered gives you one.
    """

    rotation: str = "fixed"           # "fixed" | "rotating"
    orientation: str = "always_same"  # "always_same" | "per_side"; fixed only
    centered: bool = False            # Valorant's "Keep Player Centered"

    _ROTATION = ("fixed", "rotating")
    _ORIENTATION = ("always_same", "per_side")

    def __post_init__(self) -> None:
        if self.rotation not in self._ROTATION:
            raise ValueError(f"rotation must be one of {self._ROTATION}, got {self.rotation!r}")
        if self.orientation not in self._ORIENTATION:
            raise ValueError(f"orientation must be one of {self._ORIENTATION}, got {self.orientation!r}")

    @property
    def has_static_homography(self) -> bool:
        """True when minimap pixels map to world coordinates by one constant
        transform for the whole session -- the cheap case for stage 03."""
        return (
            self.rotation == "fixed"
            and self.orientation == "always_same"
            and not self.centered
        )

    def as_dict(self) -> dict:
        return {
            "rotation": self.rotation,
            "orientation": self.orientation,
            "centered": self.centered,
            "has_static_homography": self.has_static_homography,
        }

    def __str__(self) -> str:
        return f"{self.rotation}/{self.orientation}/{'centered' if self.centered else 'uncentered'}"

    @classmethod
    def parse(cls, text: str) -> "MinimapMode":
        """Parse a descriptor like "fixed/always_same/uncentered".

        Tokens are order-independent and may be separated by "/", "," or
        whitespace. Omitted tokens keep their default.
        """
        tokens = [t for t in text.replace("/", " ").replace(",", " ").split() if t]
        kw: dict = {}
        for tok in tokens:
            low = tok.lower()
            if low in cls._ROTATION:
                kw["rotation"] = low
            elif low in cls._ORIENTATION:
                kw["orientation"] = low
            elif low in ("centered", "center"):
                kw["centered"] = True
            elif low in ("uncentered", "notcentered", "off"):
                kw["centered"] = False
            else:
                known = list(cls._ROTATION) + list(cls._ORIENTATION) + ["centered", "uncentered"]
                raise SystemExit(f"unknown minimap-mode token {tok!r}; known: {', '.join(known)}")
        return cls(**kw)


@dataclass(frozen=True)
class Profile:
    name: str
    aspect: str
    rois: list[Roi] = field(default_factory=list)
    # The minimap settings this profile assumes. A capture recorded under
    # different settings is still ingestable -- pass `ingest --minimap-mode`
    # and the manifest records what was actually used.
    minimap: MinimapMode = field(default_factory=MinimapMode)
    # Where toggled on-screen readouts may appear. Not necessarily occupied --
    # this is the envelope, and what is actually switched on is measured per
    # capture.
    overlay_zones: list[OverlayZone] = field(default_factory=list)

    @property
    def roi_names(self) -> list[str]:
        return [r.name for r in self.rois]


VALORANT_16_9 = Profile(
    name="valorant-16x9",
    aspect="16:9",
    rois=[
        # Top-left tactical map. Changes constantly during a live round as
        # player dots move -- the strongest in-match signal available without
        # a trained classifier. Bounds are the minimap widget circle
        # (px 18..335, 25..345 at 1920x1080), not the map geometry, which
        # varies per map inside that circle.
        Roi("minimap", 0.008, 0.020, 0.180, 0.325),
        # Round score and timer, top centre (px 810..1110, 30..70).
        Roi("scoreline", 0.420, 0.020, 0.580, 0.075),
        # Friendly roster portraits and health pips (px 435..750, 22..100).
        # Unlike hud_hp / hud_ammo this survives your own death, so it is the
        # chrome signal that separates "dead, still in the round" from "not in
        # a match at all". Portraits right-align toward the scoreline as
        # teammates die, so edge density here scales with how many are alive.
        Roi("hud_roster", 0.226, 0.020, 0.391, 0.093),
        # Killfeed stack, top right. Entries are right-aligned to px ~1899 and
        # the longest run left to px ~1440; they stack downward from y~90 in
        # ~41px rows. NOTE: Valorant's "shooting error" HUD widget sits inside
        # this box (px 1750..1890, 215..280) and holds a constant edge floor
        # here even with an empty feed -- matters for stage 02 killfeed OCR.
        Roi("killfeed", 0.740, 0.075, 0.995, 0.320),
        # Health and shields. Bottom HUD is CENTRE-anchored, not corner-
        # anchored: shield pip + HP digits sit at px 515..680, 990..1055.
        Roi("hud_hp", 0.268, 0.917, 0.354, 0.977),
        # Ammo counter, immediately right of the ability row (px 1255..1400).
        # Nowhere near the bottom-right corner -- that holds the weapon name
        # and credit total.
        Roi("hud_ammo", 0.654, 0.917, 0.729, 0.977),
        # Crosshair region. Low texture when scoped or in a menu.
        Roi("center", 0.460, 0.450, 0.540, 0.550),
    ],
    # Grant's settings from 2026-08-23 onward: fixed rotation, one orientation
    # for both sides, player not centred. This is the cheap case -- one
    # constant minimap -> world transform for the whole session.
    minimap=MinimapMode(rotation="fixed", orientation="always_same", centered=False),
    overlay_zones=PERF_OVERLAY_ZONES,
)

# ---------------------------------------------------------------------------
# Cropped captures.
#
# OBS composites a 2560x1440 game onto a 1920x1080 canvas at 1:1 scale, anchored
# top-left, unless you tell it to scale the source to the canvas. The recording
# is then the top-left 75% x 75% of the game frame: the bottom HUD row and the
# right-hand column never make it into the file.
#
# Measured against "2026-08-23 16-51-47.mp4" (Abyss, unrated): the crosshair and
# every screen-centred overlay sit at (1280, 720) in a 1920x1080 frame, which is
# the centre of a 2560x1440 render. Game fractions map to video fractions by
# x4/3, and anything at a game fraction above 0.75 is simply not in the file.
#
# hud_hp (game y 0.88) and hud_ammo (game x 0.78) are both outside the crop, so
# they are absent here rather than misplaced -- no coordinate fixes them. The
# killfeed is right-aligned to game x=2560 and is cut off too. What survives is
# the minimap, the top-centre scoreline, and the roster bar, so the roster bar
# stands in as the "HUD chrome is on screen" signal the segmenter gates on.
#
# This profile describes a broken capture. Fix the OBS scaling and record
# against VALORANT_16_9 instead.
VALORANT_16_9_CROP75 = Profile(
    name="valorant-16x9-crop75",
    aspect="16:9",
    rois=[
        # Minimap circle, measured directly off the capture (px 19..431, 40..460).
        Roi("minimap", 0.010, 0.030, 0.228, 0.430),
        # Left score, round timer and right score (px 1040..1490, 45..108).
        Roi("scoreline", 0.540, 0.038, 0.780, 0.100),
        # Friendly roster portraits and health pips (px 576..1075, 27..130).
        # High-contrast HUD line art that is present in a round and gone in
        # agent select, loading and the desktop -- the crop's stand-in for the
        # hud_hp / hud_ammo chrome test.
        Roi("hud_roster", 0.300, 0.025, 0.560, 0.120),
        # Crosshair region, recentred on the true viewport centre (1280, 720).
        Roi("center", 0.613, 0.600, 0.720, 0.733),
    ],
    # Captures from this era used side-based orientation: the minimap flips
    # 180 degrees at halftime, so there is no single session-wide transform.
    minimap=MinimapMode(rotation="fixed", orientation="per_side", centered=False),
)


PROFILES: dict[str, Profile] = {p.name: p for p in (VALORANT_16_9, VALORANT_16_9_CROP75)}
DEFAULT_PROFILE = VALORANT_16_9.name


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise SystemExit(f"unknown profile {name!r}; known profiles: {known}")
