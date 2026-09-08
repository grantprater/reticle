"""Where the static map geometry lives: one npz per (map, profile).

Geometry is a property of the LEVEL and the widget it is drawn in, not of the
recording. It was keyed by session until 2026-09-07, and the store's own numbers
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

A session with no `map:` tag resolves to nothing. That is deliberate: the old
layout let such a session hold a private geometry whose map nobody could name,
which is how two Ascent clips ended up outside every map-level check.
"""
from __future__ import annotations

import json
from pathlib import Path

from .store import DEFAULT_STORE

SEP = "__"


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


def path(k: str, store: str | Path = DEFAULT_STORE) -> Path:
    return Path(store) / "geometry" / f"{k}.npz"


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
    p = path(k, store)
    if not p.is_file():
        raise SystemExit(f"no geometry for {k} -- run "
                         f"prototypes/minimap_geometry.py {k}")
    return p


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
