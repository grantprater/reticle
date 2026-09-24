"""Which combat report panels were shown, which round each summarises, and what
their flags say about the player's kills, deaths and assists in that round.

Recomputed from stored `combat_report` rows; decodes no video. The reader
(`reticle.combat_report`) stores what each sampled frame shows. This module
groups frames into panels, votes each field across a panel's frames, assigns
the panel to a round, and compares its counts with the round's stored killfeed
counts. Where a report was shown its counts are the round's VERDICT, and the
killfeed count and the disagreement are stored beside it; a round with no
report takes the killfeed's count, marked as such. The report reproduced the
known K/D on `a06f04a0059f` and `3694746e4e54` where the killfeed did not, and
its disagreements with the killfeed are the killfeed reader's error list.

Panels and rounds
-----------------
* A **panel episode** is a run of frames with the header found, split at gaps
  over `GAP_MS` (a reopen with N, or the round summary later).
* An episode that starts at a player death (`rounds.player_death_times`) is a
  new **death panel**. Two rounds can read identically (one 160 headshot each),
  so a death always starts a new panel.
* Any other episode is a **reopen** of the previous panel when its damage
  numbers match it (damage reads are stable across frames; hit counts are
  not), else a new **summary panel** [domain:combat_report/round-summary].
* A summary that opens within `SUMMARY_WINDOW_MS` of a round's start with no
  death near it summarises the PREVIOUS round.

Owns [owns:combat-report-round].
"""
from __future__ import annotations

from collections import Counter

from ..version import COMBAT_REPORT_ROUND_VERSION, COMBAT_REPORT_VERSION

HEADER_MIN = 0.70            # header correlation that counts as a panel shown
FLAG_MIN = 0.70              # flag-word correlation that counts as drawn
GAP_MS = 3000.0
DEATH_BEFORE_MS, DEATH_AFTER_MS = 5000.0, 2000.0
SUMMARY_WINDOW_MS = 45000.0
ROUND_TAIL_MS = 8000.0       # a panel this long after a round's end still belongs to it
FIELDS = ("out", "in", "out_hits", "in_hits")


def episodes(frames: list[dict]) -> list[list[dict]]:
    out, cur = [], []
    for r in frames:
        if r.get("kind") != "frame" or (r.get("header") or 0) < HEADER_MIN or "rows" not in r:
            continue
        if cur and r["t_ms"] - cur[-1]["t_ms"] > GAP_MS:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def frame_read(r: dict) -> tuple:
    """A frame's damage and hit texts per row: the unit panels vote on."""
    return tuple(tuple(row[f]["text"] for f in FIELDS) for row in r["rows"])


def _vote(frames: list[dict]) -> tuple[tuple, list[dict]]:
    """The episode's modal read and the frames that show it."""
    by = {}
    for r in frames:
        by.setdefault(frame_read(r), []).append(r)
    return max(by.items(), key=lambda kv: len(kv[1]))


def _flags(frames: list[dict], k: int) -> dict[str, bool]:
    votes: dict[str, list[bool]] = {}
    for r in frames:
        row = r["rows"][k]
        for side in ("out_word", "in_word"):
            for w, v in row.get(side, {}).items():
                votes.setdefault(f"{side[:-5]}:{w}", []).append(v >= FLAG_MIN)
    return {key: sum(v) * 2 > len(v) for key, v in votes.items()}


def _agreement(frames: list[dict], read: tuple) -> dict[str, list[int]]:
    """Per field, frames agreeing with the mode, disagreeing, and refused."""
    out = {f: [0, 0, 0] for f in FIELDS}
    for r in frames:
        for k, mode in enumerate(read):
            if len(r["rows"]) <= k:
                continue
            for i, f in enumerate(FIELDS):
                v = r["rows"][k][f]["text"]
                out[f][2 if v is None else 0 if v == mode[i] else 1] += 1
    return out


def panels(frames: list[dict], death_times: list[float]) -> list[dict]:
    out = []
    for e in episodes(frames):
        read, shown = _vote(e)
        if not read:
            continue
        t0 = e[0]["t_ms"]
        at_death = any(t0 - DEATH_BEFORE_MS <= d <= t0 + DEATH_AFTER_MS for d in death_times)
        dmg = [(o, i) for o, i, _, _ in read]
        if out and not at_death and dmg == [(o, i) for o, i, _, _ in out[-1]["read"]]:
            out[-1]["reopens"].append(t0)
            continue
        flags = [_flags(shown, k) for k in range(len(read))]
        out.append({
            "start_ms": t0, "end_ms": e[-1]["t_ms"], "at_death": at_death,
            "frames": len(e), "modal_frames": len(shown), "read": read,
            "agreement": _agreement(e, read), "reopens": [],
            "rows": [{**dict(zip(FIELDS, vals)),
                      "killed": f.get("out:KILLED", False),
                      "assist": f.get("out:ASSIST", False),
                      "killed_you": f.get("in:KILLED YOU", False)}
                     for vals, f in zip(read, flags)],
        })
    return out


def assign_rounds(ps: list[dict], rounds: list[dict]) -> None:
    """Set each panel's `round_no` and `kind` in place; null with a reason
    where no round contains it."""
    rounds = sorted(rounds, key=lambda r: r["t_start_ms"])
    for p in ps:
        t0 = p["start_ms"]
        cur = [r for r in rounds if r["t_start_ms"] <= t0 <= r["t_end_ms"] + ROUND_TAIL_MS]
        rnd = cur[-1] if cur else None
        p["kind"] = "death" if p["at_death"] else "summary"
        if rnd is not None and not p["at_death"] and t0 - rnd["t_start_ms"] < SUMMARY_WINDOW_MS:
            prev = [r for r in rounds if r["t_end_ms"] <= rnd["t_start_ms"]]
            rnd = prev[-1] if prev else None
        p["round_no"] = rnd["round_no"] if rnd else None
        p["round_reason"] = None if rnd else "no round contains the panel"


def round_counts(ps: list[dict], rounds: list[dict]) -> list[dict]:
    """Per round: the report's counts beside the stored killfeed counts."""
    out = []
    for r in sorted(rounds, key=lambda r: r["round_no"]):
        mine = [p for p in ps if p["round_no"] == r["round_no"]]
        row = {"round_no": r["round_no"], "t_start_ms": r["t_start_ms"],
               "t_end_ms": r["t_end_ms"], "panels": [p["start_ms"] for p in mine],
               "stored_kills": r.get("player_kills"), "stored_deaths": r.get("player_deaths")}
        if not mine:
            row.update({"kills": None, "deaths": None, "assists": None,
                        "reason": "no panel shown for this round"})
        else:
            # The last panel of a round carries its full set of rows; a death
            # panel carries the killer, whichever panel is last.
            last = mine[-1]
            row.update({
                "kills": sum(x["killed"] for x in last["rows"]),
                "assists": sum(x["assist"] for x in last["rows"]),
                "deaths": max(sum(x["killed_you"] for x in p["rows"]) for p in mine),
                "reason": None})
        row["kills_agree"] = (None if row["kills"] is None or row["stored_kills"] is None
                              else row["kills"] == row["stored_kills"])
        row["deaths_agree"] = (None if row["deaths"] is None or row["stored_deaths"] is None
                               else row["deaths"] == row["stored_deaths"])
        # The verdict: the report where one was shown, else the killfeed.
        # The report totalled the known K/D on both sessions checked where
        # the killfeed did not; the killfeed count stays beside it.
        if row["kills"] is not None:
            row.update({"kills_verdict": row["kills"], "deaths_verdict": row["deaths"],
                        "verdict_source": "combat_report"})
        else:
            row.update({"kills_verdict": row["stored_kills"], "deaths_verdict": row["stored_deaths"],
                        "verdict_source": "killfeed" if row["stored_kills"] is not None else None})
        out.append(row)
    return out


def events(session_id: str, frames: list[dict], rounds: list[dict],
           death_times: list[float]) -> list[dict]:
    versions = Counter(r.get("combat_report_version") for r in frames if r.get("kind") == "frame")
    if set(versions) != {COMBAT_REPORT_VERSION}:
        raise ValueError(f"combat_report rows are {dict(versions)}, current is {COMBAT_REPORT_VERSION}")
    ps = panels(frames, death_times)
    assign_rounds(ps, rounds)
    per_round = round_counts(ps, rounds)
    common = {"session_id": session_id, "source": "combat_report",
              "combat_report_round_version": COMBAT_REPORT_ROUND_VERSION,
              "combat_report_version": COMBAT_REPORT_VERSION}
    seen = [r for r in per_round if r["kills"] is not None]
    head = {**common, "kind": "summary", "panels": len(ps), "rounds": len(per_round),
            "rounds_with_panel": len(seen),
            "kills": sum(r["kills"] for r in seen),
            "deaths": sum(r["deaths"] for r in seen),
            "assists": sum(r["assists"] for r in seen),
            "kills_disagree": sum(r["kills_agree"] is False for r in seen),
            "deaths_disagree": sum(r["deaths_agree"] is False for r in seen),
            "kills_verdict": sum(r["kills_verdict"] or 0 for r in per_round),
            "deaths_verdict": sum(r["deaths_verdict"] or 0 for r in per_round),
            "verdict_from_killfeed": sum(r["verdict_source"] == "killfeed" for r in per_round)}
    return ([head]
            + [{**common, "kind": "panel", **{k: v for k, v in p.items() if k != "read"}} for p in ps]
            + [{**common, "kind": "round", **r} for r in per_round])
