"""Which combat report panels were shown, which round each summarises, and what
their flags say about the player's kills, deaths and assists in that round.

Recomputed from stored `combat_report` rows; decodes no video. The reader
(`reticle.combat_report`) stores what each sampled frame shows. This module
groups frames into panels, votes each field across a panel's frames, assigns
the panel to a round, and compares its counts with the round's stored killfeed
counts. Where a report was shown its counts are the round's VERDICT, and the
killfeed count and the disagreement are stored beside it. A round with no
report takes the player's own K/D for the round from `adjudication.self_entry`
(`own_counts`): its own entries (source `self_entry`), else the round's "Me"
killfeed count on a capture that prints "Me" (source `killfeed`), else no
verdict, `None` with the owner's reason (`verdict_reason`), on a capture that
prints the account name. The report reproduced the
known K/D on `a06f04a0059f` and `3694746e4e54` where the killfeed did not, and
its disagreements with the killfeed are the killfeed reader's error list.

Panels and rounds
-----------------
* A **panel episode** is a run of frames with the header found, split at gaps
  over `GAP_MS` (a reopen with N, or the round summary later).
* An episode that opens at a player death (`rounds.player_death_times`, in
  `near_death`'s window) is a new **death panel**. Two rounds can read
  identically (one 160 headshot each), so a new death always starts a new
  panel; a death opens at most one, so an episode that repeats the previous
  death panel's read with no later death in its window is that panel's reopen.
* Any other episode is a **reopen** of the previous panel when its damage
  numbers match it (damage reads are stable across frames; hit counts are
  not), else a new **summary panel** [domain:combat_report/round-summary].
* A summary that opens within `SUMMARY_WINDOW_MS` of a round's start with no
  death near it summarises the PREVIOUS round.

Naming rows
-----------
`name_rows` groups rows across panels by their portrait thumbnails (one
player's art repeats) and asks `adjudication.identity` for each group's agent.
The witnesses are the killfeed portraits of the entries the report's flags bind
to -- the killer on the player's death for a panel's one KILLED YOU row, the victim of the
player's single kill for a lone KILLED row -- kept only where the scoreboard's
kill or death increments over the round admit that agent, and the scoreboard
itself where those increments admit exactly one. On the player's 50 labelled
rows of `a06f04a0059f` this named 49 with no error; the gallery match on the
report's own portrait named 28 right of 37 and is not used.

Owns [owns:combat-report-round].
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from ..version import COMBAT_REPORT_ROUND_VERSION, COMBAT_REPORT_VERSION

HEADER_MIN = 0.70            # header correlation that counts as a panel shown
FLAG_MIN = 0.70              # flag-word correlation that counts as drawn
GAP_MS = 3000.0
#: A panel opens with the death, but the killfeed can read the death late:
#: on `b3b9defb6fd7` at 1635 s the death flash washed the killfeed plates and
#: the entry was first read 2.5 s after the panel opened. One window serves
#: every rule that ties a panel to a death (`near_death`).
DEATH_BEFORE_MS, DEATH_AFTER_MS = 5000.0, 4000.0
SUMMARY_WINDOW_MS = 45000.0
FIELDS = ("out", "in", "out_hits", "in_hits")


def near_death(t0: float, death_ms: float) -> bool:
    """Whether a death read at `death_ms` belongs to a panel opening at `t0`:
    from `DEATH_BEFORE_MS` before it opens to `DEATH_AFTER_MS` after. The
    at-death call, the death binding and the killer's killfeed track all use
    it, and `panels` also uses it to fold a repeated read with no later death
    into a reopen; when binding kept its own window, 2 panels called at-death
    on `223d636bf8d2` and `c40d950031bb` bound no death. The death stream's
    onset can precede the HUD death time by up to 6 s, so a panel called
    at-death can still miss its death verdict (`59c70f1ef720` 1625 s). The
    other such panel, `5822b6646448` 1093 s, repeated the 1087 s death panel
    and is now its reopen."""
    return t0 - DEATH_BEFORE_MS <= death_ms <= t0 + DEATH_AFTER_MS


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


def death_panel_tops(frames: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Times (ms) and screen tops (rows) of the stored frames that show a death
    panel: the header found (HEADER_MIN) and a row flagging KILLED YOU
    (FLAG_MIN). Only the player's death opens one
    [domain:combat_report/appears-on-death], and only a death panel draws
    the KILLED BY box and the killer's card, whose top lies
    `combat_report.KILLED_BY_TOP` rows above the header: a summary for a round
    the player survived (b3b9defb6fd7 430 s, 1770 s) flags no KILLED YOU and
    draws neither. `checks.panel_slots` places the panel over the killfeed.

    ValueError on a stream reread from the crop cache's one-frame-per-round
    set (`thinned`): its frames give the round's counts, not the panel's
    timing."""
    from ..combat_report import KILLED_BY_TOP
    why = thinned(frames)
    if why is not None:
        raise ValueError(why)
    fr = [r for r in frames if r.get("kind") == "frame"]
    n = len(fr)
    if not n:
        return np.zeros(0), np.zeros(0)
    # Stored rows are dicts; gather each field once into flat arrays, then
    # decide with numpy. A frame's rows are flattened with their frame index.
    header = np.fromiter((r.get("header") or 0 for r in fr), dtype=float, count=n)
    hy = np.array([r.get("hy") for r in fr], dtype=float)          # None -> nan
    cand = np.flatnonzero((header >= HEADER_MIN) & ~np.isnan(hy))
    rows = [fr[i].get("rows") or () for i in cand]
    counts = np.fromiter(map(len, rows), dtype=np.int64, count=len(cand))
    flag = np.fromiter(((row.get("in_word") or {}).get("KILLED YOU", 0)
                        for rs in rows for row in rs), dtype=float, count=int(counts.sum()))
    best = np.full(len(cand), -np.inf)
    np.maximum.at(best, np.repeat(np.arange(len(cand)), counts), flag)
    shown = cand[best >= FLAG_MIN]
    t = np.fromiter((fr[i]["t_ms"] for i in shown), dtype=float, count=len(shown))
    return t, hy[shown] + KILLED_BY_TOP


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
        for side in ("out_word", "in_word", "slot_word"):
            for w, v in row.get(side, {}).items():
                votes.setdefault(f"{side.split('_')[0]}:{w}", []).append(v >= FLAG_MIN)
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
    """Group episodes into panels (see the module docstring).

    A death opens at most one death panel. An episode in a death's window
    whose damage read equals the previous death panel's, with no death in its
    own window later than that panel's deaths, is a reopen of that panel: on
    `5822b6646448` round 12 the report showed at 1087 s for one frame, hid,
    and showed the same read at 1093 s, and the HUD death at 1088 s sat in
    both windows. A death after the previous panel's still opens a new panel,
    however alike the reads."""
    out = []
    for e in episodes(frames):
        read, shown = _vote(e)
        if not read:
            continue
        t0 = e[0]["t_ms"]
        mine = [d for d in death_times if near_death(t0, d)]
        at_death = bool(mine)
        dmg = [(o, i) for o, i, _, _ in read]
        same = bool(out) and dmg == [(o, i) for o, i, _, _ in out[-1]["read"]]
        if same and at_death and out[-1]["at_death"]:
            held = max(d for d in death_times if near_death(out[-1]["start_ms"], d))
            at_death = any(d > held for d in mine)
        if same and not at_death:
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
                      "killed_you": f.get("in:KILLED YOU", False),
                      # ALLY in the weapon slot: damage to or from a teammate
                      # [domain:combat_report/ally-damage-row].
                      "ally": f.get("slot:ALLY", False),
                      "portrait": shown[len(shown) // 2]["rows"][k].get("portrait")}
                     for k, (vals, f) in enumerate(zip(read, flags))],
        })
    return out


def assign_rounds(ps: list[dict], rounds: list[dict]) -> None:
    """Set each panel's `round_no` and `kind` in place; null with a reason
    where no round contains it.

    The round containing a panel's opening is the rounds owner's
    (`rounds.round_containing` over `build_rounds` rows, which carry
    `t_close_ms`): the post-round period belongs to the round just decided
    [domain:rounds/post-round-period], up to the next buy phase. Until
    combat-report-round-0.11.0 this module kept its own window, a fixed 8 s
    past the round's end, which disagreed with the owner wherever the
    post-round gap was not 8 s.

    The panel's own rule is the summary step: a summary shows in the next
    buy phase [domain:combat_report/round-summary], so one that opens early
    in a round (within `SUMMARY_WINDOW_MS` of its start) reports the previous
    round, and one that opens within that window after the LAST stored
    round's close reports that round, whose next round the capture cut off
    before its score changed (`75a55a296d3b` 1230 s, in round 13's buy
    phase after round 12)."""
    from ..rounds import round_containing
    rounds = sorted(rounds, key=lambda r: r["t_start_ms"])
    for p in ps:
        t0 = p["start_ms"]
        rnd = round_containing(t0, rounds)
        p["kind"] = "death" if p["at_death"] else "summary"
        if (rnd is None and not p["at_death"] and rounds
                and 0 <= t0 - rounds[-1]["t_close_ms"] < SUMMARY_WINDOW_MS):
            rnd = rounds[-1]
        elif rnd is not None and not p["at_death"] and t0 - rnd["t_start_ms"] < SUMMARY_WINDOW_MS:
            prev = [r for r in rounds if r["t_end_ms"] <= rnd["t_start_ms"]]
            # A round's rows do not change between the death and its end
            # [domain:combat_report/frozen-after-death], so the summary of a
            # round the player died in reads that death panel's damage. A panel
            # that reads otherwise is this round's own: a death the killfeed
            # never counted (`c62c2b06bcfb` 1144 s, KILLED BY KILLJOY at 1:27).
            # A panel no round holds yet has no kind; with no previous round
            # nothing died in it.
            died = [q for q in ps if prev and q is not p and q.get("round_no") == prev[-1]["round_no"]
                    and q.get("kind") == "death"]
            dmg = lambda q: [(r["out"], r["in"]) for r in q["rows"]]
            if prev and died and dmg(died[-1]) != dmg(p)[:len(dmg(died[-1]))]                     and any(r["killed_you"] for r in p["rows"]):
                p["kind"] = "death"
                p["kind_reason"] = "killed_you_without_killfeed_death"
            else:
                rnd = prev[-1] if prev else None
        p["round_no"] = rnd["round_no"] if rnd else None
        p["round_reason"] = None if rnd else "no round contains the panel"


def own_counts(store, session_id: str, rounds: list[dict]) -> tuple[dict, dict[int, dict]]:
    """The player's own K/D, session and per round of `rounds`, from
    `adjudication.self_entry` (`session_kd`, `round_kd`), the rounds' "Me"
    killfeed counts handed it as its second witness."""
    from .self_entry import round_kd, session_kd
    kd = session_kd(store, session_id, {"kills": sum(r["player_kills"] for r in rounds),
                                        "deaths": sum(r["player_deaths"] for r in rounds)})
    return kd, round_kd(kd, rounds)


#: `verdict_source` of a reportless round by the self-entry owner's basis.
OWN_SOURCE = {"self_entry": "self_entry", "me": "killfeed"}


def round_counts(ps: list[dict], rounds: list[dict],
                 own: dict[int, dict] | None = None) -> list[dict]:
    """Per round: the report's counts beside the stored killfeed counts.
    `own` is `own_counts`' per-round answer; without it a reportless round
    takes the stored killfeed count, as before the owner existed."""
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
                # KILLED on an ALLY row is a team kill, which the scoreboard
                # does not count (`043bafca271a` 1892 s).
                "kills": sum(x["killed"] and not x.get("ally") for x in last["rows"]),
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
                        "verdict_source": "combat_report", "verdict_reason": None})
        elif own is not None:
            o = own.get(r["round_no"]) or {}
            read = o.get("kills") is not None
            row.update({"kills_verdict": o.get("kills"), "deaths_verdict": o.get("deaths"),
                        "verdict_source": OWN_SOURCE.get(o.get("basis")) if read else None,
                        "verdict_reason": None if read else (o.get("reason") or "no_own_count"),
                        "unread_kills": o.get("unread_kills"),
                        "unread_deaths": o.get("unread_deaths")})
        else:
            row.update({"kills_verdict": row["stored_kills"], "deaths_verdict": row["stored_deaths"],
                        "verdict_source": "killfeed" if row["stored_kills"] is not None else None,
                        "verdict_reason": None})
        out.append(row)
    return out


def events(session_id: str, frames: list[dict], rounds: list[dict],
           death_times: list[float], own: tuple[dict, dict[int, dict]] | None = None
           ) -> list[dict]:
    """The `combat_report_round` stream. `own` is `own_counts`' answer, which
    a reportless round takes; the summary records its basis and stamp."""
    versions = Counter(r.get("combat_report_version") for r in frames if r.get("kind") == "frame")
    if set(versions) != {COMBAT_REPORT_VERSION}:
        raise ValueError(f"combat_report rows are {dict(versions)}, current is {COMBAT_REPORT_VERSION}")
    ps = panels(frames, death_times)
    assign_rounds(ps, rounds)
    per_round = round_counts(ps, rounds, own[1] if own is not None else None)
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
            "verdict_from_killfeed": sum(r["verdict_source"] == "killfeed" for r in per_round),
            "verdict_from_self_entry": sum(r["verdict_source"] == "self_entry" for r in per_round),
            "verdict_unread": sum(r["kills_verdict"] is None for r in per_round)}
    if own is not None:
        from .self_entry import SELF_ENTRY_VERSION
        head["own_basis"], head["own_reason"] = own[0]["basis"], own[0]["reason"]
        head.setdefault("inputs", {})["self_entry"] = SELF_ENTRY_VERSION
    return ([head]
            + [{**common, "kind": "panel", **{k: v for k, v in p.items() if k != "read"}} for p in ps]
            + [{**common, "kind": "round", **r} for r in per_round])


def round_verdicts(stream: list[dict], rounds: list[dict]) -> dict:
    """The per-round verdict a consumer reads, or a refusal with its reason.

    `stream` is the stored `combat_report_round` events and `rounds` the
    caller's current rounds. The verdict was assigned against the rounds of its
    own run, so it is refused -- never silently read -- when its stamp is not
    current or when any round's bounds or killfeed counts have changed since.
    Each round carries `kills`, `deaths` (the verdict), `assists` (report only,
    else None), `source` (combat_report or killfeed) and the killfeed counts beside it.
    Names are not here: a row's agent is `adjudication.identity`'s verdict.
    """
    if not stream:
        return {"status": "refused", "reason": "no_report", "rounds": {}}
    stamp = stream[0].get("combat_report_round_version")
    if stamp != COMBAT_REPORT_ROUND_VERSION:
        return {"status": "refused", "reason": f"stale_verdict {stamp}", "rounds": {}}
    got = [r for r in stream if r.get("kind") == "round"]
    now = {r["round_no"]: r for r in rounds}
    changed = [r["round_no"] for r in got
               if r["round_no"] not in now
               or (r["t_start_ms"], r["t_end_ms"], r["stored_kills"], r["stored_deaths"])
               != (now[r["round_no"]]["t_start_ms"], now[r["round_no"]]["t_end_ms"],
                   now[r["round_no"]]["player_kills"], now[r["round_no"]]["player_deaths"])]
    if changed or len(got) != len(now):
        return {"status": "refused", "reason": f"rounds_changed {changed or 'count'}",
                "rounds": {}}
    return {"status": "ok", "reason": None, "rounds": {
        r["round_no"]: {"kills": r["kills_verdict"], "deaths": r["deaths_verdict"],
                        "assists": r["assists"], "source": r["verdict_source"],
                        "reason": r.get("verdict_reason"),
                        "killfeed_kills": r["stored_kills"], "killfeed_deaths": r["stored_deaths"],
                        "agree": r["kills_agree"] is not False and r["deaths_agree"] is not False}
        for r in got}}


#: The per-round fields `round_frames` checks its kept frames reproduce:
#: what `round_verdicts` hands a consumer.
VERDICT_FIELDS = ("kills", "deaths", "assists", "kills_verdict", "deaths_verdict",
                  "verdict_source")
#: How stable a candidate frame is, best first: both neighbouring samples
#: read the same, one does, or neither (`round_frames`).
STABILITY = ("interior", "pair", "single")


def _owned_rounds(frames: list[dict], rounds: list[dict], death_times: list[float]
                  ) -> tuple[list[dict], dict[float, dict]]:
    """The panels of `frames` with their rounds, and each episode's panel
    keyed by the episode's first time: a panel's own or one of its reopens."""
    ps = panels(frames, death_times)
    assign_rounds(ps, rounds)
    return ps, {t0: p for p in ps for t0 in [p["start_ms"]] + p["reopens"]}


def _verdicts(frames: list[dict], rounds: list[dict], death_times: list[float]
              ) -> tuple[dict, dict[float, int | None]]:
    """Per round, the `VERDICT_FIELDS` the panels of `frames` give; and per
    frame time, the round its panel was assigned to."""
    ps, owner = _owned_rounds(frames, rounds, death_times)
    got = {r["round_no"]: tuple(r[f] for f in VERDICT_FIELDS) for r in round_counts(ps, rounds)}
    where = {}
    for e in episodes(frames):
        p = owner.get(e[0]["t_ms"])
        for f in e:
            where[f["t_ms"]] = None if p is None else p["round_no"]
    return got, where


def round_frames(frames: list[dict], rounds: list[dict], death_times: list[float]) -> list[dict]:
    """Per round, the stored frames that hold its report, or none and why:
    one frame for each damage read its panels show.

    The combat report does not change within a round (the player,
    2026-10-05; [domain:combat_report/frozen-after-death]), so a round whose
    panels all read the same damage keeps one frame. Where the stored rows
    say it changed, each read keeps its own frame: on `b7d24102a6f6` round 18
    a one-row death panel at 1859 s preceded a three-row panel at 1912 s, and
    one frame of the second lost the first's row. Panels with the same
    damage read (`panels`' reopen test) are one read; hit counts may differ.

    Candidates are the frames of the episodes this module assigns to the
    round (`panels`, `assign_rounds`) that read their episode's modal damage
    and hit texts (`frame_read`) and its voted flags. They rank by stability
    (`STABILITY`: both neighbouring samples read the same, then one, then
    neither), then by row count, then the round summary first
    [domain:combat_report/round-summary] (a frame at or after the round's
    end, earliest first), then the frozen post-death panel, earliest first,
    so the frame opens near the death that `near_death` binds.

    The choice is checked against this module: the kept frames alone must
    give every round the verdict all the frames give (`VERDICT_FIELDS`), and
    each kept frame must land in its own round. Each read of a round that
    fails moves to its next candidate until none fails or it has none left;
    it then keeps its best and says `reproduces: false`. A round whose reads
    together never reproduce keeps the one read that does, if any, and names
    the panels it dropped (`reads_dropped`). A round with no candidate keeps
    nothing, with the reason.

    The kept frames carry the round's counts, not the panel's timing: a
    stream reread from them answers `round_verdicts` and refuses
    `death_panel_tops` and row naming (`thinned`)."""
    frames = sorted((r for r in frames if r.get("kind") == "frame"), key=lambda r: r["t_ms"])
    rounds = sorted(rounds, key=lambda r: r["t_start_ms"])
    by_no = {r["round_no"]: r for r in rounds}
    t_all = np.asarray([r["t_ms"] for r in frames], float)
    step = float(np.median(np.diff(t_all))) if len(t_all) > 1 else 1000.0
    ps, owner = _owned_rounds(frames, rounds, death_times)
    # One slot per round and damage read, in the order the reads first show.
    cands: dict[tuple[int, tuple], list[tuple[tuple, dict, dict]]] = {}
    for e in episodes(frames):
        p = owner.get(e[0]["t_ms"])
        read, shown = _vote(e)
        if p is None or p["round_no"] is None or not read:
            continue
        rnd = by_no[p["round_no"]]
        slot = (p["round_no"], tuple((o, i) for o, i, _, _ in read))
        flags = [_flags(shown, k) for k in range(len(read))]
        ok = np.array([frame_read(f) == read
                       and [_flags([f], k) for k in range(len(read))] == flags for f in e])
        t = np.asarray([f["t_ms"] for f in e], float)
        near = np.diff(t) <= 1.5 * step
        left = np.r_[False, ok[:-1] & near]
        right = np.r_[ok[1:] & near, False]
        tier = np.where(left & right, 0, np.where(left | right, 1, 2))
        for i in np.flatnonzero(ok):
            summary = bool(t[i] >= rnd["t_end_ms"])
            key = (int(tier[i]), -len(read), 0 if summary else 1, float(t[i]))
            cands.setdefault(slot, []).append((key, e[i], {
                "stability": STABILITY[int(tier[i])], "rows": len(read),
                "shown": "summary" if summary else "in_round",
                "episode_ms": [float(t[0]), float(t[-1])], "panel_ms": p["start_ms"],
                "panel_kind": p["kind"]}))
    for v in cands.values():
        v.sort(key=lambda c: c[0])
    want, _ = _verdicts(frames, rounds, death_times)

    def check(pick):
        kept = sorted((cands[s][k][1] for s, k in pick.items()), key=lambda r: r["t_ms"])
        got, where = _verdicts(kept, rounds, death_times)
        return {s for s, k in pick.items()
                if got.get(s[0]) != want.get(s[0]) or where.get(cands[s][k][1]["t_ms"]) != s[0]}

    def search(slots):
        pick = {s: 0 for s in slots}
        while True:
            bad = check(pick)
            move = [s for s in bad if pick[s] + 1 < len(cands[s])]
            if not move:
                break
            for s in move:
                pick[s] += 1
        if bad:
            # A read that never reproduced keeps its best candidate; the
            # check reruns on the frames kept.
            for s in bad:
                pick[s] = 0
            bad = check(pick)
        return pick, {s[0] for s in bad}

    pick, bad = search(list(cands))
    # A round whose reads cannot all reproduce its verdict keeps the one read
    # that does, best ranked first, and names the reads it dropped: the
    # panels' rounds hang on each other (a summary early in a round reports
    # the previous one unless that round's death panel reads otherwise), so
    # an extra frame can move a verdict the full stream gave.
    dropped: dict[int, list[float]] = {}
    for no in sorted(bad):
        mine = sorted((s for s in pick if s[0] == no), key=lambda s: cands[s][0][0])
        for s in mine if len(mine) > 1 else ():
            p2, b2 = search([x for x in pick if x[0] != no] + [s])
            if no not in b2 and len(b2) < len(bad):
                dropped[no] = sorted(cands[x][0][2]["panel_ms"] for x in mine if x != s)
                pick, bad = p2, b2
                break
    reason = {r["round_no"]: r["reason"] for r in round_counts(ps, rounds)}
    out = []
    for r in rounds:
        no = r["round_no"]
        mine = [s for s in pick if s[0] == no]
        if not mine:
            out.append({"round_no": no, "t_ms": None, "frame_idx": None,
                        "reason": reason.get(no) or "no frame reads its panel's modal read"})
            continue
        got = []
        for s in mine:
            k = pick[s]
            _key, f, info = cands[s][k]
            got.append({"round_no": no, "t_ms": float(f["t_ms"]), "frame_idx": int(f["frame_idx"]),
                        "reason": None, **info, "reads": len(mine),
                        "reads_dropped": dropped.get(no, []), "candidates": len(cands[s]),
                        "rank": k, "reproduces": no not in bad})
        out.extend(sorted(got, key=lambda c: c["t_ms"]))
    return out


def thinned(rows: list[dict] | None) -> str | None:
    """Why a stored `combat_report` stream cannot stand for every sampled
    frame, or None where it can.

    A stream reread from the crop cache's `combat_report` set holds the
    frames `round_frames` kept and a `thinned_out` refusal at every other
    frame. It gives each round its counts, but not when or how long the
    death panel showed, nor each panel's opening, kind and rows.
    `death_panel_tops`, `panel_aside` and row naming refuse it with this
    reason."""
    head = next((r for r in rows or () if r.get("kind") == "coverage"), None)
    gate = (head or {}).get("cache_gate") or {}
    gone = (head or {}).get("frames_refused")
    if gate or any(r.get("reason") == "thinned_out" for r in rows or ()
                   if r.get("kind") == "frame"):
        return (f"thinned: reread from the {(head or {}).get('cache_set') or 'combat_report'} "
                f"crop set ({gate.get('rule') or 'gated'}), {gone if gone is not None else 'some'} "
                f"frames refused; the death panel's timing needs every frame")
    return None


#: Thumbnail correlation joining two rows to one player.
PORTRAIT_SAME = 0.8
#: No kill happens this early in a round, so reads before it are "before".
BUY_PHASE_MS = 25000.0
KF_SLACK_MS = 500.0


def _corr(a, b) -> float:
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


def portrait_clusters(ps: list[dict]) -> None:
    """Set `cluster` on every row in place: a row whose thumbnail correlates at
    `PORTRAIT_SAME` with a cluster's first row joins it; None without one."""
    from ..combat_report import thumbnail_array
    # Both teams may field one agent, so an ALLY row never joins an enemy
    # row's cluster however alike the art.
    reps: list[tuple[bool, np.ndarray]] = []
    for p in ps:
        for row in p["rows"]:
            if not row.get("portrait"):
                row["cluster"] = None
                continue
            t = thumbnail_array(row["portrait"]).astype(np.float32)
            ally = bool(row.get("ally"))
            for i, (side, r) in enumerate(reps):
                if side == ally and _corr(r, t) >= PORTRAIT_SAME:
                    row["cluster"] = i
                    break
            else:
                reps.append((ally, t))
                row["cluster"] = len(reps) - 1


def _stat(board, agent, key, lo, hi, last):
    vals = [b for b in board if b["agent"] == agent and b[key] is not None and lo <= b["t"] <= hi]
    if not vals:
        return None
    return (max if last else min)(vals, key=lambda b: b["t"])[key]


def scoreboard_bound(board, enemy, a, after_lo, close) -> tuple[set, set]:
    """Enemies whose deaths and whose kills rose between the last read before
    the buy phase ends and the first read after `after_lo`."""
    died, killed = set(), set()
    for ag in enemy:
        for key, bucket in (("deaths", died), ("kills", killed)):
            b = _stat(board, ag, key, 0, a + BUY_PHASE_MS, last=True)
            f = _stat(board, ag, key, after_lo, close + 2 * BUY_PHASE_MS, last=False)
            if b is not None and f is not None and f > b:
                bucket.add(ag)
    return died, killed


def _killfeed_name(track, portraits, role, split, gallery):
    from .identity import claim_from_killfeed_portrait
    votes = Counter()
    for o in portraits:
        # The killer on the player's death and the victim of the player's kill
        # are both enemies. Without this the slot match took the PLAYER's own
        # killer portrait from the kill entry above a death, which the enemy
        # candidates then read as Iso: four KILLED YOU rows on `a06f04a0059f`.
        if (o.get("role") == role and o.get("ally") is False and o.get("slot") == track["slot"]
                and track["t_first"] - KF_SLACK_MS <= o["t_ms"] <= track["t_last"] + KF_SLACK_MS):
            c = claim_from_killfeed_portrait(o, entity_id="kf", candidates=split["named"],
                                             rivals=split["rivals"], gallery=gallery)
            if c["agent"]:
                votes[c["agent"]] += 1
    top = votes.most_common(2)
    if not top or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def lone_killed_you(p: dict) -> bool:
    """Whether a panel carries exactly one KILLED YOU row. A death has one
    killer, so only then does the panel's one death -- its verdict or its
    killer's killfeed track -- name that row. `bind_deaths` and `name_rows`
    both ask this."""
    return sum(bool(row.get("killed_you")) for row in p["rows"]) == 1


def _killer_plan(p, mine, earlier) -> dict[int, tuple]:
    """Which death each KILLED YOU row of a death panel binds to:
    {row: (death, extra evidence, other death entities it rests on)}.

    One row binds to the panel's one death in its window. With two or more
    rows, a row whose portrait cluster an earlier death panel of the round
    bound to death D binds to D, and then the one row left binds to the one
    death in the window that no row of the panel holds. `earlier` maps a
    cluster to the killer bindings earlier death panels of the round made.
    Rows share no binding: two rows in one cluster, or two rows bound to one
    death, refuse the panel; a cluster bound to two deaths binds nothing by
    cluster; more than one row or death left leaves the rest unbound."""
    ky = [k for k, row in enumerate(p["rows"]) if row.get("killed_you")]
    if lone_killed_you(p):
        return {ky[0]: (mine[0], {"rule": "one_killed_you_row"}, [])} if len(mine) == 1 else {}
    clusters = [p["rows"][k].get("cluster") for k in ky]
    if any(c is not None and clusters.count(c) > 1 for c in clusters):
        return {}
    plan = {}
    for k, c in zip(ky, clusters):
        prior = earlier.get(c, [])
        if len({b["death"]["death_id"] for b in prior}) == 1:
            b = prior[0]
            plan[k] = (b["death"], {"rule": "earlier_panel_cluster", "cluster": c,
                                    "earlier_panel_start_ms": b["panel_start_ms"],
                                    "earlier_row": b["row"]}, [])
    held = [d["death_id"] for d, _, _ in plan.values()]
    if len(set(held)) < len(held):
        return {}
    rest = [k for k in ky if k not in plan]
    left = [d for d in mine if d["death_id"] not in held]
    if len(rest) == 1 and len(left) == 1:
        plan[rest[0]] = (left[0], {"rule": "remaining_death"},
                         sorted(f"{h}:killer" for h in held))
    return plan


def bind_deaths(ps, rounds, death_rows) -> tuple[list[dict], list[dict]]:
    """Bind report rows to stored death verdicts (`reticle deaths`), and the
    identity claims that binding carries.

    A death panel's KILLED YOU rows bind to the player's deaths -- not second
    lives or revives -- as entity `<death_id>:killer`, by `_killer_plan`:

    * A panel with one KILLED YOU row binds it to the one death first seen in
      the panel's `near_death` window, the one `panels` calls it at-death by.
    * The report is cumulative over a round, so a panel after a revive lists
      both killers. On `a1a995e6b19b` round 7 KAY/O killed the player at
      632.5 s, a revive followed at 634 s and Deadlock killed the player at
      638 s; the 633 s panel bound KAY/O's portrait cluster to the 632.5 s
      death, and the 638 s panel showed both killers with only the 638 s death
      in its window. Such a row binds by its portrait cluster to the death an
      earlier death panel of the round bound that cluster to, and the one row
      left binds to the one death in the window no row holds. The cluster,
      not the arbiter's name, selects the death, so the rule never picks a
      death by a name that rests on the same portraits. When clusters are
      unbound or shared, or more than one death is left, the rest stay
      unbound; 0.9.0 bound every row of such a panel to the later death's
      killer (`b3b9defb6fd7` 891 s and 1308 s, `b7d24102a6f6` 1912 s too).

    A lone KILLED row binds to the player's lone kill in the round (before
    the panel, for a death panel), as `<death_id>`.
    Each binding publishes the death entity's name on the row's cluster with
    `depends_on` that entity -- and, for the row left over, the deaths the
    other rows hold: the death's name rests on the same killfeed portraits, so
    it can disagree but is never independent. Returns (bindings, claims);
    rows with no or several candidates are not bound.
    """
    from .identity import identity_claim
    by_no = {r["round_no"]: r for r in rounds}
    deaths = [d for d in death_rows if d.get("kind") == "death_verdict" and not d.get("is_revive")]
    bindings, claims = [], []
    # (round_no, cluster) -> the killer bindings earlier death panels made.
    earlier: dict[tuple, list[dict]] = {}
    for p in ps:
        rnd = by_no.get(p.get("round_no"))
        if rnd is None:
            continue
        a, close = rnd["t_start_ms"], rnd.get("t_close_ms") or rnd["t_end_ms"]
        mine = [d for d in deaths if d["kf_player_death"] and not d["is_second_life"]
                and near_death(p["start_ms"], d["t_ms"])]
        kills = [d for d in deaths if d["kf_player_kill"] and a <= d["t_ms"] < close
                 and (p["kind"] != "death" or d["t_ms"] <= p["start_ms"])]
        killed = [k for k, row in enumerate(p["rows"]) if row.get("killed")]
        plan = {}
        if p["kind"] == "death":
            plan = _killer_plan(p, mine, {c: v for (n, c), v in earlier.items()
                                          if n == p["round_no"]})
        for k, row in enumerate(p["rows"]):
            if row.get("entity_id") is None:
                continue
            if k in plan:
                d, extra, rests_on = plan[k]
                role, key, entity = "killer", "killer_identity", f"{d['death_id']}:killer"
                if row.get("cluster") is not None:
                    earlier.setdefault((p["round_no"], row["cluster"]), []).append(
                        {"death": d, "panel_start_ms": p["start_ms"], "row": k})
            elif row.get("killed") and len(killed) == 1 and len(kills) == 1:
                d, role, key = kills[0], "victim", "identity"
                entity, extra, rests_on = d["death_id"], {"rule": "lone_kill"}, []
            else:
                continue
            verdict = d["metadata"].get(key) or {}
            name = verdict.get("agent") if verdict.get("status") == "resolved" else None
            bindings.append({"panel_start_ms": p["start_ms"], "row": k, "role": role,
                             "entity_id": row["entity_id"], "death_entity": entity,
                             "rule": extra["rule"]})
            claims.append(identity_claim(
                row["entity_id"], name, channel="death_verdict", binding_from="combat_report",
                observed_at_ms=p["start_ms"], depends_on=[entity, *rests_on],
                source_version=d.get("death_adjudication_version"),
                evidence={"panel_start_ms": p["start_ms"], "row": k, "role": role,
                          "death_entity": entity, **extra},
                reason=None if name else f"death {role} {verdict.get('status', 'unread')}"))
    return bindings, claims


def ally_bound(ally_rows, player) -> list[str]:
    """Teammates an ALLY row can be: the ally lineup's named agents minus the
    player. Guns never damage allies, so a row's weapon never narrows it."""
    return sorted({r["agent"] for r in ally_rows if r.get("agent")} - {player})


def name_rows(session_id, ps, rounds, kill_tracks, death_tracks, portraits, board,
              enemy_rows, gallery, death_rows=(), ally_rows=(), player=None):
    """Identity claims and verdicts for report rows, keyed by portrait cluster.

    `board` is one dict per enemy scoreboard row read: t, agent, kills, deaths.
    `kill_tracks` and `death_tracks` are the player's counted killfeed tracks;
    `portraits` the stored killfeed portrait observations. `death_rows` is the
    stored `death` stream; given it, `bind_deaths` binds KILLED YOU and lone
    KILLED rows to death entities and sets `death_entity` on them. An ALLY row
    takes no enemy witness; `ally_rows` (the lineup's ally side) less `player`
    bounds it. Each panel
    row gets `entity_id`; the name lives only in the arbiter's verdicts.
    """
    from ..killfeed import KILLFEED_PORTRAIT_VERSION
    from .identity import adjudicate_agent_identity, identity_claim, side_candidates
    portrait_clusters(ps)
    split = side_candidates(enemy_rows)
    enemy = split["named"]
    by_no = {r["round_no"]: r for r in rounds}
    claims = []
    for p in ps:
        for row in p["rows"]:
            row["entity_id"] = (None if row.get("cluster") is None
                                else f"combat_report:{session_id}:portrait:{row['cluster']}")
        rnd = by_no.get(p.get("round_no"))
        if rnd is None:
            continue
        a = rnd["t_start_ms"]
        close = rnd.get("t_close_ms") or rnd["t_end_ms"]
        after_lo = p["start_ms"] if p["kind"] == "death" else rnd["t_end_ms"]
        died, killed = scoreboard_bound(board, enemy, a, after_lo, close)
        kills = [t for t in kill_tracks if a <= t["t_first"] < close
                 and (p["kind"] != "death" or t["t_first"] <= p["start_ms"])]
        death = [t for t in death_tracks if p["kind"] == "death"
                 and near_death(p["start_ms"], t["t_first"])]
        victims = {_killfeed_name(t, portraits, "victim", split, gallery) for t in kills} - {None}
        # The killer's track names a KILLED YOU row only when the panel has
        # one: after a revive the panel lists both killers, and the last
        # track's name belongs to one of them (`b7d24102a6f6` 1912 s).
        killer = (_killfeed_name(death[-1], portraits, "killer", split, gallery)
                  if death and lone_killed_you(p) else None)
        lone_kill = sum(r["killed"] for r in p["rows"]) == 1 and len(kills) == 1
        for k, row in enumerate(p["rows"]):
            if row["entity_id"] is None:
                continue
            if row.get("ally"):
                # A teammate: no enemy witness applies. The lineup names it
                # only when one teammate remains; a team kill in the killfeed
                # names it through `bind_deaths`.
                bound = ally_bound(ally_rows, player)
                claims.append(identity_claim(
                    row["entity_id"], bound[0] if len(bound) == 1 else None,
                    channel="ally_lineup", observed_at_ms=p["start_ms"],
                    evidence={"panel_start_ms": p["start_ms"], "row": k, "ally_bound": bound},
                    reason=None if len(bound) == 1 else f"ally bound of {len(bound)}: {bound}"))
                continue
            if row["killed_you"]:
                name, bound, role = killer, killed, "killer"
            elif row["killed"] and lone_kill and len(victims) == 1:
                name, bound, role = next(iter(victims)), died, "victim"
            elif row["killed"]:
                name, bound, role = None, died, "victim"
            else:
                continue
            evidence = {"panel_start_ms": p["start_ms"], "row": k, "role": role,
                        "scoreboard_bound": sorted(bound)}
            if name is not None:
                inside = not bound or name in bound
                claims.append(identity_claim(
                    row["entity_id"], name if inside else None, channel="killfeed_portrait",
                    binding_from="combat_report", observed_at_ms=p["start_ms"],
                    source_version=KILLFEED_PORTRAIT_VERSION, evidence=evidence,
                    reason=None if inside else f"outside scoreboard bound {sorted(bound)}"))
            if len(bound) == 1:
                claims.append(identity_claim(
                    row["entity_id"], next(iter(bound)), channel="scoreboard_kd",
                    binding_from="combat_report", observed_at_ms=p["start_ms"],
                    evidence=evidence))
    bindings, bound = bind_deaths(ps, rounds, death_rows)
    for b in bindings:
        ps_row = next(p for p in ps if p["start_ms"] == b["panel_start_ms"])["rows"][b["row"]]
        ps_row["death_entity"] = b["death_entity"]
    claims += bound
    return claims, adjudicate_agent_identity(claims)
