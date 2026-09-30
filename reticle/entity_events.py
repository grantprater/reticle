"""The entity-event projection and its read API: stage 1, not yet built.

[owns:entity-event]. `docs/ENTITY_EVENTS.md` is the plan. This module will
hold `project_lane`, which copies what each owner stored into the one schema
`entity_contract` declares and writes each lane's consumer output and
ledger, and `EntityEvents`, the only door a consumer reads events through
(`architecture.toml`, `[consumers]`). Stage 0 places it and declares its
lanes; it projects nothing yet.

It decides nothing. It invents no key, name, time or position; a threshold,
a margin or a vote belongs to an owner, and two owners that disagree go to
the ledger side by side. A projected event is never stored back as evidence.
Every name it copies comes from a resolved verdict of `adjudication.identity`,
so a lane that copies a name rests on the arbiter: `NAME_ARBITER` is the
arbiter stamp this declaration was written against.
"""
from __future__ import annotations

from .adjudication.identity import AGENT_IDENTITY_VERSION

#: The arbiter every naming lane rests on; a change to it rebuilds each lane
#: whose `names` is true (plan section 3, "Version stamp and staleness").
NAME_ARBITER = AGENT_IDENTITY_VERSION

#: The lanes, in the plan's order: minimap and screen lanes first, audio
#: last. `inputs` are the stored streams each reads; a lane waiting on an
#: owner that does not exist says so in `waits_for`.
ENTITY_LANES: tuple[dict, ...] = (
    {"lane": "round_entity", "order": 1, "channel": "minimap", "names": True,
     "inputs": ("round_entity", "rounds")},
    {"lane": "death", "order": 1, "channel": "killfeed, HUD, scoreboard", "names": True,
     "inputs": ("death", "death_identity", "rounds")},
    {"lane": "spike", "order": 1, "channel": "minimap, round table", "names": False,
     "inputs": ("rounds", "spike_carrier")},
    {"lane": "players", "order": 2, "channel": "arbiter over every channel", "names": True,
     "inputs": ("rounds",), "waits_for": "the arbiter's stored side verdict (gap 1)"},
    {"lane": "smoke", "order": 2, "channel": "minimap", "names": True,
     "inputs": ("smoke", "smoke_owner", "smoke_owner_identity", "rounds")},
    {"lane": "ping", "order": 2, "channel": "minimap", "names": False,
     "inputs": ("ping", "rounds")},
    {"lane": "enemy", "order": 2, "channel": "minimap", "names": True,
     "inputs": (), "waits_for": "an enemy icon owner and a last-known mark owner (gap 3)"},
    {"lane": "slot_state", "order": 3, "channel": "tray", "names": True,
     "inputs": ("ability_state", "tray_kit", "tray_kit_identity")},
    {"lane": "ult_cast", "order": 4, "channel": "audio", "names": True,
     "inputs": ("ult_cast", "ult_cast_identity", "rounds")},
    {"lane": "disagreement", "order": None, "channel": "every channel", "names": False,
     "inputs": ("spike_carrier",),
     "waits_for": "reconciliation's stored disagreements as a stream"},
)
