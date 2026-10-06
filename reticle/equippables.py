"""What kind of equippable dealt a hit: gun, melee or ability, by where the
game keeps its class.

[owns:equippable-kind]

A replay names the equippable behind each damage record by class
(`AssaultRifle_AK_C`, `Ability_Phoenix_4_Molotov_Production_C`). The build's
asset index places every class: guns under
`ShooterGame/Content/Equippables/Guns/`, the knife under
`Equippables/Melee/`, an agent's abilities under `Characters/<Agent>/`.
This module reads that placement, ignoring case (a replay's class name and
the index can differ in case); it restates no list of weapon names. A class
the index lacks is `unread`; no class at all (fall damage, the spike's
blast) is `none`.
"""
from __future__ import annotations

import gzip
from functools import lru_cache
from pathlib import Path

from .store import DEFAULT_STORE
from .wall_penetration import build_root

EQUIPPABLES_VERSION = "equippables-0.1.0"
KINDS = ("gun", "melee", "ability", "other", "none", "unread")

_PREFIX = (("ShooterGame/Content/Equippables/Guns/", "gun"),
           ("ShooterGame/Content/Equippables/Melee/", "melee"),
           ("ShooterGame/Content/Characters/", "ability"))


@lru_cache(maxsize=2)
def _class_kinds(root: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with gzip.open(build_root(root) / "index.tsv.gz", "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            p, _, c = line.rstrip("\n").partition("\t")
            if c != "BlueprintGeneratedClass":
                continue
            kind = next((k for pre, k in _PREFIX if p.startswith(pre)), "other")
            name = (Path(p).stem + "_C").lower()
            if out.get(name) in (None, "other"):
                out[name] = kind
    return out


def equippable_kind(cls: str | None, root=DEFAULT_STORE) -> str:
    """`gun`, `melee`, `ability`, `other`, `none` (no class) or `unread`."""
    if cls is None or str(cls) in ("", "None"):
        return "none"
    return _class_kinds(str(root)).get(str(cls).lower(), "unread")
