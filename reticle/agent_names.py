"""How an agent's name is spelt, and whether two spellings name one agent.

Owns [owns:agent-spelling].

The stores spell one agent several ways. The official reference and the tray's
glyph gallery say `KAY/O`; asset filenames cannot hold "/", so the art, the
lineup and the identity arbiter say `KAY_O`; a manifest tag says `kayo`. A
comparison letter for letter between two of them fails silently: the tray's
`KAY/O` met the lineup's `KAY_O` in `adjudication.identity` and left the
player of c817691bcd15 and d3dcfb182ab1 bound to no slot, so every own-cast
stream ran without him.

Every agent-name comparison in `reticle/` asks this module:

* `canonical_agent` -- the one stored spelling, the asset stem (`KAY_O`);
  `adjudication.identity.identity_claim` stores every name in it.
* `agent_key` -- the comparison key, case and punctuation dropped (`kayo`).
* `same_agent` -- whether two names are one agent, None where either is
  unknown.
* `reference_agent` -- the spelling a keyed collection (the reference's
  agents, a gallery) uses for a name, found by key, never by a table.

It decides spelling only. Which agent an entity is belongs to
`adjudication.identity`; this module holds no agent list and no alias table.
"""

from __future__ import annotations

import re
from typing import Iterable

_NON_KEY = re.compile(r"[^a-z0-9]")


def canonical_agent(name: str | None) -> str | None:
    """The stored spelling of an agent name: stripped, with "/" spelt "_" as
    the asset filenames spell it (`KAY/O` is `KAY_O`). None stays None."""
    if name is None:
        return None
    return str(name).strip().replace("/", "_")


def agent_key(name: str | None) -> str:
    """The comparison key of a name: casefolded, letters and digits only, so
    `KAY/O`, `KAY_O` and `kayo` share `kayo`. None keys as ""."""
    return _NON_KEY.sub("", str(name or "").casefold())


def same_agent(a: str | None, b: str | None) -> bool | None:
    """Whether two agent names are one agent across every spelling; None
    where either is unknown (None or empty)."""
    ka, kb = agent_key(a), agent_key(b)
    if not ka or not kb:
        return None
    return ka == kb


def agent_in(name: str | None, names: Iterable[str]) -> bool:
    """Whether `name` is one of `names`, compared by `agent_key`."""
    k = agent_key(name)
    return bool(k) and any(agent_key(n) == k for n in names)


def reference_agent(name: str | None, names: Iterable[str]) -> str | None:
    """The member of `names` (a reference's or gallery's keys) that spells
    `name`'s agent, or None where none does. An exact match wins."""
    names = list(names)
    if name in names:
        return name
    k = agent_key(name)
    if not k:
        return None
    return next((n for n in names if agent_key(n) == k), None)
