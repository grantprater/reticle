"""What a code change leaves stale, and the least work that refreshes it.

Every stored stream carries the stamp of the code that wrote it; `stale`
compares each with the stamp the code carries now, per session. A stale
reader stream needs a decode, and `scan --only <channel>` rereads only that
channel's readers; a reader with a trial (`trial.TRIAL_READERS`) can be
checked first on stored windows without one. A stale adjudication rereads
nothing: it reruns from storage. A stream never written is `absent`, which
is not stale.

A stamp is only as good as the bump: a code change that keeps its stamp is
invisible here, as it is to `scan`'s cache check.
"""
from __future__ import annotations

from collections import defaultdict

import pyarrow.parquet as pq


def _table_stamp(path, key: str) -> str | None:
    if not path.is_file():
        return None
    meta = pq.read_schema(path).metadata or {}
    return meta.get(key.encode(), b"").decode() or "unstamped"


def _death_stamps(store, sid: str) -> str | None:
    rows = store.read_events("death", sid)
    if not rows:
        return None
    head = rows[0]
    return (head.get("death_adjudication_version"), head.get("inputs") or {})


def reader_streams() -> list[tuple[str, str, str, str | None]]:
    """(stream, scan channel, current stamp, trial reader or None)."""
    from .killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
    from .version import (ALLY_ICON_VERSION, COMBAT_REPORT_VERSION, HUD_VERSION,
                          MINIMAP_DARK_VERSION, MINIMAP_VERSION, PING_VERSION,
                          ROSTER_VERSION, SCOREBOARD_VERSION)
    return [("hud", "hud", HUD_VERSION, None),
            ("killfeed_portrait", "hud", KILLFEED_PORTRAIT_VERSION, "killfeed"),
            ("killfeed_weapon", "hud", KILLFEED_WEAPON_VERSION, "killfeed"),
            ("minimap", "minimap", MINIMAP_VERSION, None),
            ("roster", "roster", ROSTER_VERSION, None),
            ("ping", "ping", PING_VERSION, None),
            ("ally_icon", "ally_icon", ALLY_ICON_VERSION, None),
            ("minimap_dark", "minimap_dark", MINIMAP_DARK_VERSION, None),
            ("combat_report", "combat_report", COMBAT_REPORT_VERSION, None),
            ("scoreboard", "scoreboard", SCOREBOARD_VERSION, None)]


def stored_stamp(store, manifest: dict, stream: str) -> str | None:
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    if stream == "hud":
        return _table_stamp(store.hud_path(sid, date), "hud_version")
    if stream == "minimap":
        return _table_stamp(store.minimap_path(sid, date), "minimap_version")
    if stream == "roster":
        return _table_stamp(store.roster_path(sid, date), "roster_version")
    return store.events_version(stream, sid)


def stale(store, sessions: list[str]) -> dict:
    """Per session: stale reader streams (decode), stale adjudications
    (storage only), and absent streams."""
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    from .killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
    from .version import HUD_VERSION
    out = {}
    for sid in sessions:
        man = store.read_manifest(sid)
        decode, derived, absent = [], [], []
        for stream, channel, now, trial in reader_streams():
            got = stored_stamp(store, man, stream)
            if got is None:
                absent.append(stream)
            elif got != now:
                decode.append({"stream": stream, "channel": channel, "stored": got,
                               "current": now, "trial": trial})
        d = _death_stamps(store, sid)
        if d is not None:
            version, inputs = d
            want = {"hud": HUD_VERSION, "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
                    "killfeed_weapon": KILLFEED_WEAPON_VERSION}
            moved = sorted(k for k, v in want.items() if inputs.get(k) not in (v, None))
            # An input the rescan will rewrite moves too, once it has run.
            moved += sorted(s["stream"] for s in decode if s["stream"] in want
                            and s["stream"] not in moved)
            if version != DEATH_ADJUDICATION_VERSION or moved:
                derived.append({"stream": "death", "stored": version,
                                "current": DEATH_ADJUDICATION_VERSION, "inputs_moved": moved,
                                "command": f"reticle deaths {sid}"})
        out[sid] = {"decode": decode, "derived": derived, "absent": absent}
    return out


def render(plan: dict) -> str:
    """The stale work grouped by what refreshes it, with the commands."""
    by_channel: dict[str, list[str]] = defaultdict(list)
    trials: dict[str, list[str]] = defaultdict(list)
    derived = []
    for sid, p in plan.items():
        for s in p["decode"]:
            if sid not in by_channel[s["channel"]]:
                by_channel[s["channel"]].append(sid)
            if s["trial"] and sid not in trials[s["trial"]]:
                trials[s["trial"]].append(sid)
        derived += [(sid, d) for d in p["derived"]]
    lines = []
    if not by_channel and not derived:
        return f"nothing stale over {len(plan)} sessions"
    for ch, sids in sorted(by_channel.items()):
        streams = sorted({s["stream"] for p in plan.values() for s in p["decode"]
                          if s["channel"] == ch})
        lines.append(f"decode   {ch}: {', '.join(streams)} stale on {len(sids)} sessions")
        for t, tsids in sorted(trials.items()):
            if set(tsids) & set(sids):
                lines.append(f"  check  reticle trial {tsids[0]} --reader {t} --from cache"
                             f"   (one session, stored windows, no decode)")
        lines.append(f"  accept reticle scan <sid> --only {ch}   for {' '.join(sids)}")
    for sid, d in derived:
        why = (f"{d['stored']} -> {d['current']}" if d["stored"] != d["current"]
               else "inputs " + ", ".join(d["inputs_moved"]))
        lines.append(f"storage  {d['command']}   ({why})")
    return "\n".join(lines)
