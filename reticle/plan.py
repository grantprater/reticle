"""What a code change leaves stale, and the least work that refreshes it.

Every stored stream carries the stamp of the code that wrote it; `stale`
compares each with the stamp the code carries now, per session. A stale
reader stream needs a reread, and `scan --only <channel>` rereads only that
channel's readers; the `audio` channel is `ult-lines`, which decodes only
the audio stream (`ACCEPT`). A reader with a trial (`trial.TRIAL_READERS`) reads only
cached ROIs: it can be checked first on stored windows, and `scan` feeds it
from the ROI crop cache instead of decoding when a cache holds its set
(`roi_cache.cache_for`). A stale adjudication rereads
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


def _round_stamps(store, manifest: dict) -> dict | None:
    """The stamps a stored round table was built from, or None where the
    session has no round table. A table written before the portrait stamp
    was recorded reads `unrecorded`."""
    path = store.rounds_path(manifest["session_id"], manifest["ingested_at"][:10])
    if not path.is_file():
        return None
    meta = pq.read_schema(path).metadata or {}
    get = lambda k, missing: meta.get(k.encode(), missing.encode()).decode()
    return {"round": get("round_version", "unstamped"), "hud": get("hud_version", "unknown"),
            "killfeed_portrait": get("killfeed_portrait_version", "unrecorded")}


#: The command that rereads a channel `scan` does not read.
ACCEPT = {"audio": "reticle ult-lines <sid>"}


def reader_streams() -> list[tuple[str, str, str, str | None]]:
    """(stream, scan channel, current stamp, trial reader or None)."""
    from .killfeed import (KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION,
                           KILLFEED_WEAPON_VERSION)
    from .version import (ALLY_ICON_VERSION, COMBAT_REPORT_VERSION, HUD_VERSION,
                          MINIMAP_DARK_VERSION, MINIMAP_VERSION, PING_VERSION,
                          ROSTER_VERSION, SCOREBOARD_VERSION, ULT_LINE_VERSION)
    return [("hud", "hud", HUD_VERSION, "hud"),
            ("killfeed_portrait", "hud", KILLFEED_PORTRAIT_VERSION, "killfeed"),
            ("killfeed_weapon", "hud", KILLFEED_WEAPON_VERSION, "killfeed"),
            ("killfeed_name", "hud", KILLFEED_NAME_VERSION, "killfeed"),
            ("minimap", "minimap", MINIMAP_VERSION, None),
            ("roster", "roster", ROSTER_VERSION, None),
            ("ping", "ping", PING_VERSION, None),
            ("ally_icon", "ally_icon", ALLY_ICON_VERSION, None),
            ("minimap_dark", "minimap_dark", MINIMAP_DARK_VERSION, None),
            ("combat_report", "combat_report", COMBAT_REPORT_VERSION, None),
            ("scoreboard", "scoreboard", SCOREBOARD_VERSION, None),
            ("ult_line", "audio", ULT_LINE_VERSION, None)]


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
    from .killfeed import (KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION,
                           KILLFEED_WEAPON_VERSION)
    from .version import (HUD_VERSION, ROUND_VERSION, TRAY_VERSION, ULT_CAST_VERSION,
                          ULT_LINE_VERSION)
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
        rescanned = {s["stream"] for s in decode}
        rounds_stale = False
        r = _round_stamps(store, man)
        if r is not None:
            # Second lives are read only from a current portrait stream, so a
            # rebuild now would record the current stamp or none.
            portrait = (KILLFEED_PORTRAIT_VERSION if store.events_version("killfeed_portrait", sid)
                        == KILLFEED_PORTRAIT_VERSION else "none")
            moved = [k for k, v in (("hud", HUD_VERSION), ("killfeed_portrait", portrait))
                     if r[k] != v or k in rescanned]
            if r["round"] != ROUND_VERSION or moved:
                rounds_stale = True
                derived.append({"stream": "rounds", "stored": r["round"], "current": ROUND_VERSION,
                                "inputs_moved": moved, "command": f"reticle rounds {sid}"})
        d = _death_stamps(store, sid)
        if d is not None:
            version, inputs = d
            want = {"hud": HUD_VERSION, "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
                    "killfeed_weapon": KILLFEED_WEAPON_VERSION,
                    "killfeed_name": KILLFEED_NAME_VERSION, "round": ROUND_VERSION}
            moved = sorted(k for k, v in want.items() if inputs.get(k) not in (v, None))
            # An input the rescan or the round rebuild will rewrite moves too,
            # once it has run.
            moved += sorted(s for s in rescanned | ({"round"} if rounds_stale else set())
                            if s in want and s not in moved)
            if version != DEATH_ADJUDICATION_VERSION or moved:
                derived.append({"stream": "death", "stored": version,
                                "current": DEATH_ADJUDICATION_VERSION, "inputs_moved": moved,
                                "command": f"reticle deaths {sid}"})
        u = store.read_events("ult_cast", sid)
        if u:
            version, inputs = u[0].get("ult_cast_version"), u[0].get("inputs") or {}
            moved = sorted(k for k, v in (("ult_line", ULT_LINE_VERSION), ("round", ROUND_VERSION),
                                          ("tray_drop", TRAY_VERSION), ("hud", HUD_VERSION))
                           if inputs.get(k) not in (v, None))
            # The tray binding reads the HUD only where it read tray drops.
            moved += sorted(k for k, again in (("ult_line", "ult_line" in rescanned),
                                               ("round", rounds_stale),
                                               ("hud", "hud" in rescanned and "hud" in inputs))
                            if again and k not in moved)
            if version != ULT_CAST_VERSION or moved:
                derived.append({"stream": "ult_cast", "stored": version,
                                "current": ULT_CAST_VERSION, "inputs_moved": moved,
                                "command": f"reticle ult-cast {sid}"})
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
            if s["trial"] and sid not in trials[(s["channel"], s["trial"])]:
                trials[(s["channel"], s["trial"])].append(sid)
        derived += [(sid, d) for d in p["derived"]]
    lines = []
    if not by_channel and not derived:
        return f"nothing stale over {len(plan)} sessions"
    for ch, sids in sorted(by_channel.items()):
        streams = sorted({s["stream"] for p in plan.values() for s in p["decode"]
                          if s["channel"] == ch})
        cached = [t for (tch, t) in trials if tch == ch]
        lines.append(f"{'reread' if cached else 'decode'}   {ch}: {', '.join(streams)} "
                     f"stale on {len(sids)} sessions")
        for (tch, t), tsids in sorted(trials.items()):
            if tch == ch:
                lines.append(f"  check  reticle trial {tsids[0]} --reader {t} --from cache"
                             f"   (one session, stored windows, no decode)")
        accept = ACCEPT.get(ch, f"reticle scan <sid> --only {ch}")
        lines.append(f"  accept {accept}   for {' '.join(sids)}"
                     + ("   (from the ROI crop cache where one exists)" if cached else ""))
    # Grouped by command and reason, rounds before the adjudications that read them.
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, d in sorted(derived, key=lambda x: x[1]["stream"] != "rounds"):
        why = (f"{d['stored']} -> {d['current']}" if d["stored"] != d["current"]
               else "inputs " + ", ".join(d["inputs_moved"]))
        grouped[(d["command"].rsplit(" ", 1)[0], why)].append(sid)
    for (command, why), sids in grouped.items():
        lines.append(f"storage  {command} <sid>   ({why}) for {' '.join(sids)}")
    return "\n".join(lines)
