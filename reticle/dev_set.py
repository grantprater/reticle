"""The development split: the one definition every scorer imports.

The player's decision of 2026-10-09: the three 2026-10-07 replay captures
are the development set (`DEV`), because their streams are current. The old
development matches and the old held-out match are frozen at their stored
versions (`FROZEN`): their crop caches are deleted, `deaths` refuses for want
of current killfeed portraits, and the player excluded rereads of them, so
nothing can refresh them without rescanning video. They are reported only as
stale history. Held-out scoring waits for the player's next capture with a
replay; `HELD_OUT` stays empty until it arrives.

Pool names follow the sessions, never the role: `new3` is the 2026-10-07
three and `dev3` the frozen old three, as every stored metric row already
names them. A scorer may still score a frozen development match, but labels
each output from it `FROZEN_LABEL` with its stale streams named (the
harness's `extras.frozen_note`) and never pools it with `DEV` by default.
The frozen held-out match and its replay stay unread.
"""
from __future__ import annotations

from typing import Iterable

SPLIT_VERSION = "dev-split-0.2.0"

#: The development set: the 2026-10-07 replay captures.
DEV: tuple[str, ...] = ("cadaadeb2d8b", "066741deafe5", "9912c382130b")
#: The development matches until 2026-10-09, frozen at their stored versions.
FROZEN_DEV: tuple[str, ...] = ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1")
#: The held-out match until 2026-10-09, frozen and never read.
FROZEN_HELD_OUT: tuple[str, ...] = ("cea8ecbc94ab",)
#: Its replay's key prefix, which the replay layer builds and never summarises.
FROZEN_HELD_OUT_REPLAY: tuple[str, ...] = ("bd7efa02",)
FROZEN: tuple[str, ...] = FROZEN_DEV + FROZEN_HELD_OUT
#: The held-out set: empty until the player's next capture with a replay.
HELD_OUT: tuple[str, ...] = ()
#: The sessions a scorer may read: `DEV`, then the frozen development matches.
SCORABLE: tuple[str, ...] = DEV + FROZEN_DEV

#: Every output a frozen session feeds carries this label.
FROZEN_LABEL = "frozen: stale inputs"

#: Stored pool names, keyed by their sessions.
POOLS = {"new3": DEV, "dev3": FROZEN_DEV, "all6": DEV + FROZEN_DEV}


def is_frozen(sid: str) -> bool:
    return sid in FROZEN


def never_read(name: str) -> bool:
    """True for a held-out or frozen held-out session or replay key."""
    return str(name).startswith(HELD_OUT + FROZEN_HELD_OUT + FROZEN_HELD_OUT_REPLAY)


def refusal(sid: str) -> str | None:
    """Why a scorer may not read `sid`, or None when it may."""
    if never_read(sid):
        return f"{sid}: a held-out match is never read"
    if sid not in SCORABLE:
        return f"{sid}: neither a development match nor a frozen development match"
    return None


def pool_name(sessions: Iterable[str]) -> str:
    """The metrics session of a pooled scope: its stored pool name, else the
    sessions joined by `+`."""
    s = sorted(sessions)
    return next((n for n, p in POOLS.items() if s == sorted(p)), "+".join(s))


def pool_sessions(name: str) -> tuple[str, ...]:
    """The sessions a metrics session names: a pool's, a `+` join's, or itself."""
    return POOLS.get(name) or tuple(x for x in name.split("+") if x)


def frozen_in(sessions: Iterable[str]) -> list[str]:
    """The frozen sessions among `sessions`, pool names expanded and a
    suffixed metrics session (`9acf02f98283_causal`) read by its id."""
    out: list[str] = []
    for s in sessions:
        out += [x[:12] for x in pool_sessions(str(s)) if is_frozen(x[:12]) and x[:12] not in out]
    return out
