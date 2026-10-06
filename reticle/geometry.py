"""Where the static map geometry lives: one npz per (map, profile).

Geometry is a property of the LEVEL and the widget it is drawn in, not of the
recording [domain:capture/session-pixels-are-not-the-map]. It was keyed by session until 2026-09-07, and the store's own numbers
are what ended that: **36 session npz held 5 distinct geometries.** Twenty-nine
were one 39-minute Ascent match copied to twenty-eight short ability-demo clips
by a `--geometry-from` flag, because a 37s clip built around one deliberate cast
cannot median its own static map without baking the cast into it.

Three things went wrong under the old key and cannot happen under this one:

* **the copy was invisible.** A donated npz recorded nothing about its donor, so
  the relation survived only as a byte-identical `static`. Recovering it meant
  hashing every npz and guessing which member of the group was the source, and a
  rebuild that guessed wrong re-derived a demo clip from its own frames;
* **a rebuild was 36 decodes when it was really 5**, so it was deferred, so the
  stamp stayed stale, so every minimap number sat behind a `doctor` error;
* **the same map could hold different answers per session and nothing compared
  them.** The two Lotus recordings disagreed on 0.35% of pixels and their stored
  lighting references differed by 24 grey levels -- from different frame counts
  in different runs, not from the recordings, which `prototypes/CLAUDE.md`
  measured and wrote down before this module existed.

The PROFILE has to be in the key, not just the map. Every constant in
`minimap.py` is in widget pixels and the profile is what sets the minimap ROI,
so Ascent at `valorant-16x9` and Ascent at `valorant-16x9-bigmap` are different
geometries about the same level. `reference/shade/` already keyed itself this
way; this is the same key, and the two files line up by construction.

Since 2026-10-05 the npz is a cache, `<store>/geometry-official/<key>.npz`:
one map's asset, the game's own minimap textures, drawn through one profile's
transform by `reticle/map_asset.py`. No capture supplies a static pixel.
`ensure` draws a missing or stale cache in seconds; `reticle geometry` draws
every key. Capture-median geometry (`<store>/geometry/`) stays read only, and
is read only for a key whose profile has no fitted transform.

A session with no `map:` tag resolves to nothing. That is deliberate: the old
layout let such a session hold a private geometry whose map nobody could name,
which is how two Ascent clips ended up outside every map-level check.

Owns [owns:map-geometry].
"""
from __future__ import annotations

import json
from pathlib import Path

from .store import DEFAULT_STORE

SEP = "__"

#: How well the art must PLACE before its footprint is preferred to the derived
#: rule. A cut in an empty band, not a fit: over the twelve capture geometries
#: eleven placed at IoU 0.888-0.954 and one, `summit__valorant-16x9-crop75`,
#: at 0.663. A badly placed exact boundary is worse than a roughly placed
#: approximate one, so that key keeps the derived rule and `doctor` says so.
#: An official key places by its profile's transform and records 1.0.
MIN_ART_FIT = 0.80


def key(map_name: str, profile: str) -> str:
    """The geometry key for a (map, profile) pair."""
    return f"{map_name}{SEP}{profile}"


def parse(k: str) -> tuple[str, str]:
    """Split a key back into (map, profile)."""
    map_name, _, profile = k.partition(SEP)
    if not profile:
        raise ValueError(f"not a geometry key: {k!r}")
    return map_name, profile


def manifest(session: str, store: str | Path = DEFAULT_STORE) -> dict | None:
    p = Path(store) / "manifests" / f"{session}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                             # noqa: BLE001 -- a bad manifest is a missing one here
        return None


def map_of(session: str, store: str | Path = DEFAULT_STORE) -> str | None:
    """The session's map, from its manifest tags. Recorded at ingest."""
    man = manifest(session, store)
    if not man:
        return None
    return next((t.split(":", 1)[1] for t in (man.get("tags") or [])
                 if t.startswith("map:")), None)


def key_of(session: str, store: str | Path = DEFAULT_STORE) -> str | None:
    """The geometry key this session reads, or None when its map is unknown."""
    man = manifest(session, store)
    if not man:
        return None
    map_name = next((t.split(":", 1)[1] for t in (man.get("tags") or [])
                     if t.startswith("map:")), None)
    profile = man.get("source_profile")
    if not map_name or not profile:
        return None
    return key(map_name, profile)


def official_dir(store: str | Path = DEFAULT_STORE) -> Path:
    """The cache of geometry drawn from the game's files (`map_asset.render`)."""
    return Path(store) / "geometry-official"


def capture_dir(store: str | Path = DEFAULT_STORE) -> Path:
    """Capture-median geometry, read only, for a key the game's files cannot
    draw: its profile has no fitted transform."""
    return Path(store) / "geometry"


def drawable(k: str, store: str | Path = DEFAULT_STORE) -> bool:
    """Whether `map_asset` can draw the key: its map has textures and a
    rotation, and its profile a fitted transform."""
    from . import map_asset
    m, prof = parse(k)
    try:
        map_asset.textures(m, store)
        map_asset.rotation(m)
        map_asset.transform(prof)
    except SystemExit:
        return False
    return True


def path(k: str, store: str | Path = DEFAULT_STORE) -> Path:
    """The key's geometry npz: the official cache when the game's files can
    draw the key, else its capture geometry. Whether it exists or is current
    is `ensure`'s question; a reader that only loads calls this."""
    return (official_dir(store) if drawable(k, store) else capture_dir(store)) / f"{k}.npz"


#: Arrays a builder adds to a cached key from its static: the occluder table
#: (`reticle/occluders.py`) and the line classes (`prototypes/line_classes.py`).
#: `ensure` carries them across a rebuild whose static is unchanged and drops
#: them otherwise, so `doctor` reports them missing rather than stale-but-trusted.
STATIC_DERIVED = ("occ", "box_id", "box_height", "occ_boxes", "occ_lines", "occ_validation",
                  "occ_version", "occ_built_by", "lines_meta", "lines_built_by", "lines_version",
                  "lines_static_sha", "line_cls", "line_src", "line_hints", "lines_refused")


def staleness(k: str, store: str | Path = DEFAULT_STORE) -> str | None:
    """Why the key's official cache must be drawn again, or None when it is
    current or the key is not drawable."""
    import numpy as np

    from . import map_asset
    if not drawable(k, store):
        return None
    p = official_dir(store) / f"{k}.npz"
    if not p.is_file():
        return "missing"
    try:
        with np.load(p, allow_pickle=False) as z:
            got = str(z["built_by"])
    except Exception as e:                        # noqa: BLE001 -- unreadable is stale
        return f"unreadable ({type(e).__name__})"
    return None if got == map_asset.asset_stamp(*parse(k), store) else "stale built_by"


def ensure(k: str, store: str | Path = DEFAULT_STORE) -> Path:
    """The key's geometry npz, drawn from the game's files first if its cache is
    missing or stale. Decodes nothing; takes seconds."""
    import numpy as np

    from . import map_asset
    p = path(k, store)
    if staleness(k, store) is None:
        return p
    fields = map_asset.render(*parse(k), store)
    kept = {}
    if p.is_file():
        with np.load(p, allow_pickle=False) as z:
            if "static" in z.files and np.array_equal(z["static"], fields["static"]):
                kept = {n: z[n].copy() for n in STATIC_DERIVED if n in z.files}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, **fields, **kept)
    tmp.replace(p)
    return p


def writable(k: str, store: str | Path = DEFAULT_STORE) -> Path:
    """The official npz a builder may add arrays to, drawn first if needed.
    Capture geometry is read only: it is evidence, and the official build
    supersedes it rather than amending it."""
    if not drawable(k, store):
        raise SystemExit(f"{k}: the game's files cannot draw this key, and its capture "
                         f"geometry is read only")
    return ensure(k, store)


def built_keys(store: str | Path = DEFAULT_STORE) -> list[str]:
    """Every key with an official cache."""
    d = official_dir(store)
    return sorted(p.stem for p in d.glob("*.npz")
                  if SEP in p.stem and not p.stem.endswith(".tmp")) if d.is_dir() else []


def path_of(session: str, store: str | Path = DEFAULT_STORE) -> Path | None:
    """The geometry file this session reads, or None when it has no key.

    Returns the path whether or not it exists; callers that only want a built
    one should test `.is_file()`, exactly as they did when this was a session
    path. Nothing here decodes or builds.
    """
    k = key_of(session, store)
    return None if k is None else path(k, store)


def require(session: str, store: str | Path = DEFAULT_STORE) -> Path:
    """The built geometry this session reads, or a refusal that says what to do.

    For scripts that cannot proceed without it. The two failures are different
    and are reported differently: an untagged session names no map, so no
    amount of building will help it, while a tagged one is simply waiting on a
    build that now serves every session on that map.
    """
    k = key_of(session, store)
    if k is None:
        raise SystemExit(f"{session} has no `map:` tag, so it reads no geometry "
                         f"-- tag it `map:<name>` in its manifest")
    p = ensure(k, store)
    if not p.is_file():
        raise SystemExit(f"no geometry for {k}: the game's files cannot draw it "
                         f"(reticle/map_asset.py) and no capture geometry exists")
    return p


def reference_static(session: str, store: str | Path = DEFAULT_STORE):
    """The immutable base-map pixels for this session's (map, profile) key.

    A session selects a geometry key through manifest metadata; it never
    supplies or overrides these pixels.  Keep this accessor narrow so a new
    reader cannot accidentally restore the retired per-session median cache.
    Callers needing other geometry fields must name them at their own boundary.
    """
    import numpy as np

    with np.load(require(session, store), allow_pickle=False) as z:
        return z["static"].copy()


def reference_for_key(k: str, store: str | Path = DEFAULT_STORE):
    """Immutable base-map pixels for an explicit ``(map, profile)`` key.

    This is the only supported reference for bare-video prototypes, which have
    no session manifest from which to resolve a key.  Requiring the key keeps a
    convenience script from quietly turning its input clip into map geometry.
    """
    import numpy as np

    p = ensure(k, store)
    if not p.is_file():
        raise SystemExit(f"no geometry for {k}: the game's files cannot draw it "
                         f"(reticle/map_asset.py) and no capture geometry exists")
    with np.load(p, allow_pickle=False) as z:
        return z["static"].copy()


def stability(session: str, store: str | Path = DEFAULT_STORE,
              shape: tuple[int, int] | None = None):
    """This session's per-pixel `sd_lo`, for `minimap.floor_mask`'s `sd`.

    The stability map lives beside the baked reference in the geometry npz.
    Returns `None` -- meaning *no stability channel*, not
    *stable* -- for a session with no map tag, no built geometry, or a
    geometry whose widget differs in size from the caller's static map. Any of
    those keeps `floor_mask`'s pure-`med` behaviour rather than guessing.
    """
    import numpy as np

    p = path_of(session, store)
    if p is None or not p.is_file():
        return None
    with np.load(p) as z:
        if "sd_lo" not in z.files:
            return None
        sd = z["sd_lo"].copy()
    if shape is not None and tuple(sd.shape) != tuple(shape):
        return None
    return sd


def footprint(session: str, store: str | Path = DEFAULT_STORE,
              dilate: float = 1, shape: tuple[int, int] | None = None):
    """The ART footprint for this session's map, or `None` if it has none.

    `None` means *this key has no placed art*: a capture geometry without a
    shade, or one placed below MIN_ART_FIT. A caller must then fall back to
    `minimap.floor_mask` and SAY SO in its provenance. Every official key has
    one. It never means "no floor": a silent fallback is how the
    derived rule stayed in the pipeline after it was superseded.
    """
    import numpy as np

    from .minimap import art_floor
    p = path_of(session, store)
    if p is None or not p.is_file():
        return None
    with np.load(p) as z:
        if "shade_kind" not in z.files:
            return None
        if "shade_fit" in z.files and float(z["shade_fit"][4]) < MIN_ART_FIT:
            return None
        kind = z["shade_kind"].copy()
    if shape is not None and tuple(kind.shape) != tuple(shape):
        return None
    return art_floor(kind, dilate)


# ------------------------------------------------------------------ map scale

#: The configuration every base value of a map measurement is quoted at: the
#: 465 px widget at the largest map scaling [domain:capture/largest-settings-widget],
#: `minimap.REF_WIDGET_W`'s own reference. Its scale is 1 by definition.
SCALE_REF_KEY = "ascent__valorant-16x9-bigmap"
#: The wiki art ships at 1024 or 2048 px a side; `shade_fit`'s scale is widget px
#: per art px, so it is normalised to this canvas before keys are compared.
ART_CANVAS = 2048


class MapScale:
    """How one `(map, profile)` draws the map: `scale` = `widget_scale` x
    `map_zoom`, the one transform from a base value (px at SCALE_REF_KEY) to
    widget px. Readers write `ms.px(base)`, never a per-size constant.

    The widget size and the map scaling are two settings
    [domain:capture/minimap-size-settings]; `widget_scale` is the widget's
    width against `minimap.REF_WIDGET_W`, and `map_zoom` the rest of the art
    fit's scale. A variant widget is resampled into its baked frame before any
    reader sees it (`widget_frame`), so it reads its baked key's scale.

    One factor serves world drawings and icons alike. Walls, ring radii and
    line lengths mark the world and follow the zoom
    [domain:minimap/world-drawings-follow-map-zoom]; icons measured the same
    within error [domain:minimap/icons-follow-map-zoom], so there is no
    separate icon factor. Add one only if a measured icon departs from it."""

    __slots__ = ("key", "widget_scale", "map_zoom", "source")

    def __init__(self, key: str | None, widget_scale: float, map_zoom: float, source: str):
        self.key, self.widget_scale, self.map_zoom = key, float(widget_scale), float(map_zoom)
        self.source = source

    @property
    def scale(self) -> float:
        return self.widget_scale * self.map_zoom

    def px(self, base: float) -> float:
        """A base length (px at SCALE_REF_KEY) in this key's widget px."""
        return round(float(base) * self.scale, 6)

    def area(self, base: float) -> float:
        """A base area or pixel count in this key's widget px^2."""
        return round(float(base) * self.scale ** 2, 6)

    @classmethod
    def at(cls, scale: float, source: str = "given") -> "MapScale":
        """A transform of a stated scale, for synthetic crops and tests."""
        return cls(None, scale, 1.0, source)

    def provenance(self) -> dict:
        return {"key": self.key, "scale": round(self.scale, 5),
                "widget_scale": round(self.widget_scale, 5),
                "map_zoom": round(self.map_zoom, 5), "source": self.source}

    def __repr__(self) -> str:
        return f"MapScale({self.provenance()})"


def _art_side(p: Path) -> int:
    """The larger side of the map art (the files are WebP under a .png name)."""
    import cv2
    im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    return 0 if im is None else int(max(im.shape[:2]))


_SCALES: dict = {}


def _canvas_scale(k: str, store) -> tuple[float, int] | None:
    import numpy as np
    p = path(k, store)
    if not p.is_file():
        return None
    with np.load(p) as z:
        if "shade_fit" not in z.files or "shade_map" not in z.files:
            return None
        fit, name, w = z["shade_fit"].copy(), str(z["shade_map"]), int(z["static"].shape[1])
    art = Path(store) / "reference" / "maps" / f"{name}.png"
    if not art.is_file():
        return None
    return float(fit[1]) * _art_side(art) / ART_CANVAS, w


def map_scale(k: str, store: str | Path = DEFAULT_STORE) -> MapScale | None:
    """The key's transform from base values, or None when its geometry has no
    art fit (`shade_fit`); a caller then refuses by name.

    Baked data only [domain:capture/session-pixels-are-not-the-map]: the art
    fit's scale (`shade_fit[1]`, widget px per art px) times the art's side
    over ART_CANVAS is widget px per canvas px, the same quantity
    `prototypes/raised_edges.zoom` reads, taken against SCALE_REF_KEY's. An
    official key's scale is its profile's (`reticle/map_asset.py`): the 331 px
    profile draws the map at 0.638 of the reference while its widget is 0.712
    of it, so its map scaling is about 0.89 of the largest. The
    art's own world scale is not modelled: Chamber's Trademark, one world
    distance, measures 13% larger on Split than on Ascent at one scale
    [domain:abilities/chamber-trademark-minimap-white-area]."""
    from .minimap import widget_scale
    ck = (k, str(store))
    if ck not in _SCALES:
        got, ref = _canvas_scale(k, store), _canvas_scale(SCALE_REF_KEY, store)
        if got is None or ref is None:
            _SCALES[ck] = None
        else:
            ws = widget_scale(got[1])
            _SCALES[ck] = MapScale(k, ws, got[0] / ref[0] / ws,
                                   f"baked shade_fit scale x art side / {ART_CANVAS}, "
                                   f"against {SCALE_REF_KEY}")
    return _SCALES[ck]


def map_scale_of(session: str, store: str | Path = DEFAULT_STORE) -> MapScale | None:
    k = key_of(session, store)
    return None if k is None else map_scale(k, store)


def fit_path(k: str, store: str | Path = DEFAULT_STORE) -> Path:
    """The cached art-to-widget fit for a key.

    Same key as the geometry, and for the same reason: the fit is three numbers
    that depend on the map and the widget, neither of which moves within a
    session OR between two sessions of the same map at the same profile. It was
    cached per session and paid for that with 36 cache entries where 11 do.
    """
    return Path(store) / "reference" / "fits" / f"{k}.npz"


def fit_path_of(session: str, store: str | Path = DEFAULT_STORE) -> Path | None:
    k = key_of(session, store)
    return None if k is None else fit_path(k, store)


def sessions_for(k: str, store: str | Path = DEFAULT_STORE) -> list[str]:
    """Every ingested session that reads this key, longest recording first."""
    man_dir = Path(store) / "manifests"
    if not man_dir.is_dir():
        return []
    rows = []
    for f in sorted(man_dir.glob("*.json")):
        sid = f.stem
        if key_of(sid, store) != k:
            continue
        man = manifest(sid, store) or {}
        rows.append((int((man.get("source") or {}).get("frame_count") or 0), sid))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [sid for _, sid in rows]


def reference_session(k: str, store: str | Path = DEFAULT_STORE) -> str | None:
    """The session whose frames this key's geometry is built from.

    **The longest recording, and the rule matters more than the pick.** The
    static map is a per-pixel median, which assumes anything moving is a small
    minority of the sampling window -- an assumption a 37s clip built around one
    deliberate cast violates by design, and the measured cost is not subtle: on
    `79a706a7ce4c` the self-built static carried Cypher's placed camera and
    trapwires as map structure and put 347 px of "plantable" in the void beside
    A site. A 39-minute match cannot do that.

    Longest is not the only defensible rule, so it is checked rather than
    trusted: on the one key with two full matches to choose between, the longer
    also scored higher against the wiki art (SITE against derived PLANT, 85.4%
    against 85.2%), so both readings agree there.
    """
    have = sessions_for(k, store)
    return have[0] if have else None


def keys_in_store(store: str | Path = DEFAULT_STORE) -> list[str]:
    """Every key at least one ingested session reads."""
    man_dir = Path(store) / "manifests"
    if not man_dir.is_dir():
        return []
    return sorted({k for f in man_dir.glob("*.json")
                   if (k := key_of(f.stem, store)) is not None})


def untagged(store: str | Path = DEFAULT_STORE) -> list[str]:
    """Sessions that resolve to no key -- no `map:` tag, or no profile."""
    man_dir = Path(store) / "manifests"
    if not man_dir.is_dir():
        return []
    return sorted(f.stem for f in man_dir.glob("*.json")
                  if key_of(f.stem, store) is None)
