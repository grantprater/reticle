r"""The replay ability scorer's constants and census, for `acceptance replay-abilities`.

Moved from `prototypes/replay_abilities.py` on 2026-10-09 (task
`harness-t1d-20261009`). The actor reader and the class-to-ability mapping
live in `reticle.replay_actors`.
"""
from __future__ import annotations

from reticle.replay_actors import Export, ability_display, class_census, slot_map

from . import clock as rt


REPLAY_ABILITIES_VERSION = "replay-abilities-0.1.0"
STORE = rt.STORE
ANALYSIS = STORE / "analysis" / "replay-abilities-20261004"
#: A stored cast or ult pairs with a replay one within this many ms.
CAST_GATE_MS = 2000.0
ULT_GATE_MS = 3000.0


_stats = rt._stats


def actor_census(match: str, ex: Export | None = None) -> dict:
    """`reticle.replay_actors.class_census`, stamped with this scorer's version."""
    return {**class_census(match, ex), "replay_abilities_version": REPLAY_ABILITIES_VERSION}
