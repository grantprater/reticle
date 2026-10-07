"""The stored stamp of an input, as a writer records it and `plan` compares it.

A derived stream records, for every stored input it read, the stamp the
STORED input carries -- the table's metadata, the event file's first row, the
baked geometry's `built_by` -- never the code's constant for that input. A
writer that records the code's constant claims to have read a table the store
may not hold: `death` recorded `HUD_VERSION` while it read whatever HUD table
was stored.

An input the writer looked for and found no rows of is recorded `no_rows`
(`NO_ROWS`), so `plan` can tell "read, and empty" from "not read" (None)
and from "not recorded" (the key is missing): once rows exist, a stream
built over `no_rows` is stale. Older writers recorded the reasons
`no_menu_rows` and `stale:<stamp>`; `normalize` reads both as the stamp they
stand for.

These functions read stored state only, decide nothing and know no reader;
`plan` names which input each stream records (`plan.stream_inputs`).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: The stamp of an input that was read and held no rows.
NO_ROWS = "no_rows"

#: Reason strings writers recorded in place of a stamp. These mean the input
#: was read and held no rows:
_ABSENT = {"no_rows", "no_menu_rows"}
#: and these that it was not read, or read and not used for a reason that
#: names no stamp (`tray_kit`'s witness before 2026-09-30), so they compare
#: as a recorded None.
_NOT_READ = {"no_rounds", "no_lineup", "no_player_agent", "player_agent_moved"}


def normalize(recorded):
    """The stamp a recorded value stands for: `stale:<s>` -> `<s>`, an
    absent-rows reason -> `NO_ROWS`, a not-read reason -> None, anything
    else unchanged."""
    if not isinstance(recorded, str):
        return recorded
    if recorded in _ABSENT:
        return NO_ROWS
    if recorded in _NOT_READ:
        return None
    if recorded.startswith("stale:"):
        return recorded[len("stale:"):]
    return recorded


def moved(recorded, now) -> bool:
    """True when a recorded input stamp no longer matches the input's stored
    head `now`. A recorded None is an input the writer did not read."""
    recorded = normalize(recorded)
    if recorded is None:
        return False
    return recorded != normalize(now if now is not None else NO_ROWS)


def file_sha16(path) -> str | None:
    """The first 16 hex digits of a file's sha256, or None when it is absent."""
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def table_stamp(path, key: str) -> str:
    """A parquet table's metadata stamp `key`, `unstamped`, or `NO_ROWS`."""
    path = Path(path)
    if not path.is_file():
        return NO_ROWS
    import pyarrow.parquet as pq
    meta = pq.read_schema(path).metadata or {}
    return meta.get(key.encode(), b"").decode() or "unstamped"


def head_row(store, stream: str, sid: str, needle: bytes | None = None) -> dict | None:
    """The first row of a stored stream (with `needle`, the first row whose
    line holds it), without reading the rest."""
    path_of = getattr(store, "events_path", None)
    if path_of is None:     # a test store holding rows in memory
        rows = store.read_events(stream, sid)
        if needle is not None:
            rows = [r for r in rows if needle.decode() in json.dumps(r, separators=(",", ":"))]
        return rows[0] if rows else None
    path = path_of(stream, sid)
    if not path.is_file():
        return None
    with open(path, "rb") as f:
        for ln in f:
            if ln.strip() and (needle is None or needle in ln):
                return json.loads(ln)
    return None


#: The probe-field suffix that asks for a head's content stamp
#: (`content_stamp`) rather than one recorded key: `<stream>#<key>+inputs`.
CONTENT = "+inputs"


def content_stamp(head: dict | None, key: str) -> str:
    """A stored stream's content stamp: its code stamp `key` and a digest of
    the inputs its head records, `<stamp>@<16 hex>`, or `NO_ROWS`.

    A pure stream rewritten over the same inputs under the same code writes
    the same rows, so this stamp moves exactly when a rerun can change them:
    a reader of the stream that records only `key` misses a rerun over moved
    inputs (`plan.stream_inputs`, the `ability_fit` note)."""
    if head is None:
        return NO_ROWS
    blob = json.dumps(head.get("inputs"), sort_keys=True, separators=(",", ":"), default=str)
    return f"{head.get(key) or 'unstamped'}@{hashlib.sha256(blob.encode()).hexdigest()[:16]}"


def event_stamp(store, stream: str, sid: str, key: str) -> str:
    """The stamp `key` in a stored stream's first row, `unstamped`, or `NO_ROWS`."""
    head = head_row(store, stream, sid)
    if head is None:
        return NO_ROWS
    return head.get(key) or "unstamped"


def geometry_stamp(store_root, key: str | None) -> str:
    """The `built_by` of the baked geometry `key`, `unstamped`, or `NO_ROWS`
    when no npz is baked (or the session names no key)."""
    if key is None or store_root is None:
        return NO_ROWS
    from . import geometry
    path = geometry.path(key, store_root)
    if not path.is_file():
        return NO_ROWS
    import numpy as np
    with np.load(path, allow_pickle=False) as z:
        if "built_by" not in z.files:
            return "unstamped"
        b = z["built_by"]
        return str(b.item() if b.shape == () else b)
