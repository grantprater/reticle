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

Naming rows
-----------
`name_rows` groups rows across panels by their portrait thumbnails (one
player's art repeats) and asks `adjudication.identity` for each group's agent.
The witnesses are the killfeed portraits of the entries the report's flags bind
to -- the killer on the player's death for KILLED YOU, the victim of the
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
                      "killed_you": f.get("in:KILLED YOU", False),
                      "portrait": shown[len(shown) // 2]["rows"][k].get("portrait")}
                     for k, (vals, f) in enumerate(zip(read, flags))],
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
                        "killfeed_kills": r["stored_kills"], "killfeed_deaths": r["stored_deaths"],
                        "agree": r["kills_agree"] is not False and r["deaths_agree"] is not False}
        for r in got}}


#: Thumbnail correlation joining two rows to one player.
PORTRAIT_SAME = 0.8
#: No kill happens this early in a round, so reads before it are "before".
BUY_PHASE_MS = 25000.0
KF_SLACK_MS = 500.0
DEATH_LOOKBACK_MS = 6000.0


def _corr(a, b) -> float:
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


def portrait_clusters(ps: list[dict]) -> None:
    """Set `cluster` on every row in place: a row whose thumbnail correlates at
    `PORTRAIT_SAME` with a cluster's first row joins it; None without one."""
    from ..combat_report import thumbnail_array
    reps: list[np.ndarray] = []
    for p in ps:
        for row in p["rows"]:
            if not row.get("portrait"):
                row["cluster"] = None
                continue
            t = thumbnail_array(row["portrait"]).astype(np.float32)
            for i, r in enumerate(reps):
                if _corr(r, t) >= PORTRAIT_SAME:
                    row["cluster"] = i
                    break
            else:
                reps.append(t)
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


def bind_deaths(ps, rounds, death_rows) -> tuple[list[dict], list[dict]]:
    """Bind report rows to stored death verdicts (`reticle deaths`), and the
    identity claims that binding carries.

    A death panel's KILLED YOU row binds to the player's death -- not a second
    life -- first seen within `DEATH_LOOKBACK_MS` before the panel opens, as
    entity `<death_id>:killer`. A lone KILLED row binds to the player's lone
    kill in the round (before the panel, for a death panel), as `<death_id>`.
    Each binding publishes the death entity's name on the row's cluster with
    `depends_on` that entity: the death's name rests on the same killfeed
    portraits, so it can disagree but is never independent. Returns
    (bindings, claims); rows with no or several candidates are not bound.
    """
    from .identity import identity_claim
    by_no = {r["round_no"]: r for r in rounds}
    deaths = [d for d in death_rows if d.get("kind") == "death_verdict"]
    bindings, claims = [], []
    for p in ps:
        rnd = by_no.get(p.get("round_no"))
        if rnd is None:
            continue
        a, close = rnd["t_start_ms"], rnd.get("t_close_ms") or rnd["t_end_ms"]
        mine = [d for d in deaths if d["kf_player_death"] and not d["is_second_life"]
                and p["kind"] == "death"
                and p["start_ms"] - DEATH_LOOKBACK_MS <= d["t_ms"] <= p["start_ms"] + 1000]
        kills = [d for d in deaths if d["kf_player_kill"] and a <= d["t_ms"] < close
                 and (p["kind"] != "death" or d["t_ms"] <= p["start_ms"])]
        killed = [k for k, row in enumerate(p["rows"]) if row.get("killed")]
        for k, row in enumerate(p["rows"]):
            if row.get("entity_id") is None:
                continue
            if row.get("killed_you") and len(mine) == 1:
                d, role, key = mine[0], "killer", "killer_identity"
                entity = f"{d['death_id']}:killer"
            elif row.get("killed") and len(killed) == 1 and len(kills) == 1:
                d, role, key = kills[0], "victim", "identity"
                entity = d["death_id"]
            else:
                continue
            verdict = d["metadata"].get(key) or {}
            name = verdict.get("agent") if verdict.get("status") == "resolved" else None
            bindings.append({"panel_start_ms": p["start_ms"], "row": k, "role": role,
                             "entity_id": row["entity_id"], "death_entity": entity})
            claims.append(identity_claim(
                row["entity_id"], name, channel="death_verdict", binding_from="combat_report",
                observed_at_ms=p["start_ms"], depends_on=[entity],
                source_version=d.get("death_adjudication_version"),
                evidence={"panel_start_ms": p["start_ms"], "row": k, "role": role,
                          "death_entity": entity},
                reason=None if name else f"death {role} {verdict.get('status', 'unread')}"))
    return bindings, claims


def name_rows(session_id, ps, rounds, kill_tracks, death_tracks, portraits, board,
              enemy_rows, gallery, death_rows=()):
    """Identity claims and verdicts for report rows, keyed by portrait cluster.

    `board` is one dict per enemy scoreboard row read: t, agent, kills, deaths.
    `kill_tracks` and `death_tracks` are the player's counted killfeed tracks;
    `portraits` the stored killfeed portrait observations. `death_rows` is the
    stored `death` stream; given it, `bind_deaths` binds KILLED YOU and lone
    KILLED rows to death entities and sets `death_entity` on them. Each panel
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
                 and p["start_ms"] - DEATH_LOOKBACK_MS <= t["t_first"] <= p["start_ms"] + 1000]
        victims = {_killfeed_name(t, portraits, "victim", split, gallery) for t in kills} - {None}
        killer = _killfeed_name(death[-1], portraits, "killer", split, gallery) if death else None
        lone_kill = sum(r["killed"] for r in p["rows"]) == 1 and len(kills) == 1
        for k, row in enumerate(p["rows"]):
            if row["entity_id"] is None:
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
