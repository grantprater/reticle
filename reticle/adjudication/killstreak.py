"""Adjudication: the killstreak numeral as a per-round kill-count witness.

The killfeed draws a roman numeral beside a killer on a streak: which kill of
the round this entry is for that player, from the third kill on
[domain:killfeed/killstreak-indicator]. `killfeed_numeral` reads it per view
(`killfeed_numeral` stream); the death stream (`adjudication.death`) names
each entry's killer and round. The two are independent: the numeral is drawn
by the game from its own count, and the death stream counts the entries it
adjudicated. So each entry's numeral should equal its killer's kill index in
the round, counted over the death stream.

This module is pure over those two stored streams and writes a check, never a
death: a disagreement is a surprise stored with both sides, and flags a missed
kill, a false kill or a wrong killer in the death stream, or a misread
numeral. It never alters a verdict.

Pooling (`pool_entry`): one numeral per entry across the views the death
owner bound to it (the killer portrait views its killer claim cites), else
the reader's own entry follow (`entry` id) from the verdict's first view.
Two different numerals refuse as `views_disagree`; a numeral and more empty
views than numeral views refuse as `numeral_and_empty`.

Counting (`kill_indices`): a round's verdicts in time order; a kill counts
for its killer (side, agent) unless it is a revive, a second-life death or a
same-side entry, whose expected numeral is `not_counted`. An unnamed killer
on the killer's side earlier in the round makes every later index on that
side uncertain (`after_unnamed_killer`), stored and not scored.

Owns [owns:killstreak-kill-index].
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .death import DEATH_ADJUDICATION_VERSION

# 0.1.0 (2026-10-03): first witness.
KILLSTREAK_WITNESS_VERSION = "killstreak-witness-0.1.0"

#: Views a numeral (or the empty slot) must be read on to pool.
POOL_MIN_VIEWS = 2
#: The first kill index the game draws a numeral for
#: [domain:killfeed/killstreak-indicator].
FIRST_DRAWN = 3

ROMAN = {"II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
OTHER = {"ally": "enemy", "enemy": "ally"}


def roman(n: int) -> str:
    """The numeral for kill index `n`, as the reader keys it."""
    return {v: k for k, v in ROMAN.items()}[int(n)]


def pool_entry(rows: list[dict]) -> dict:
    """One reading for one entry from its views' `numeral_observation` rows:
    {numeral, reason, votes, views}. `numeral` is a numeral, "" (no numeral),
    or None with a reason."""
    votes = Counter(r["numeral"] for r in rows if r.get("numeral") is not None)
    refused = Counter(r.get("reason") for r in rows if r.get("numeral") is None)
    out = {"votes": dict(sorted(votes.items())), "refused": dict(sorted(refused.items())),
           "views": len(rows)}
    numerals = {k: v for k, v in votes.items() if k}
    if len(numerals) > 1:
        return {**out, "numeral": None, "reason": "views_disagree"}
    if numerals:
        (n, c), = numerals.items()
        if c < POOL_MIN_VIEWS:
            return {**out, "numeral": None, "reason": "too_few_views"}
        if votes.get("", 0) > c:
            return {**out, "numeral": None, "reason": "numeral_and_empty"}
        return {**out, "numeral": n, "reason": None}
    if votes.get("", 0) >= POOL_MIN_VIEWS:
        return {**out, "numeral": "", "reason": None}
    if not rows:
        return {**out, "numeral": None, "reason": "no_views"}
    return {**out, "numeral": None, "reason": "too_few_views" if votes else "no_read_view"}


def killer_views(verdict: dict) -> list[tuple[int, int]]:
    """The (frame_idx, slot) killer views the death owner bound to this
    entry: the observations its killer portrait claim cites."""
    ident = (verdict.get("metadata") or {}).get("killer_identity") or {}
    views = set()
    for c in ident.get("claims") or ():
        if c.get("channel") != "killfeed_portrait":
            continue
        for o in (c.get("evidence") or {}).get("observations") or ():
            if o.get("frame_idx") is not None and (o.get("evidence") or {}).get("slot") is not None:
                views.add((int(o["frame_idx"]), int(o["evidence"]["slot"])))
    return sorted(views)


def bind_rows(verdict: dict, rows: list[dict]) -> tuple[list[dict], str]:
    """The numeral rows of one death verdict's entry, and how they were
    bound: `killer_claim` (the death owner's killer views), else
    `reader_entry` (the reader's entry id at the verdict's first view, within
    the verdict's window), else `first_view` alone.

    The death owner's views can run onto the next entry in the same slot;
    where they span several reader entry ids, only the earliest view's entry
    is kept and the binding reads `killer_claim_first_entry`."""
    by_view = {(int(r["frame_idx"]), int(r["slot"])): r for r in rows}
    views = killer_views(verdict)
    if views:
        got = sorted((by_view[v] for v in views if v in by_view),
                     key=lambda r: (float(r["t_ms"]), int(r["slot"])))
        if got:
            ents = {r.get("entry") for r in got} - {None}
            if len(ents) > 1:
                first = next(r.get("entry") for r in got if r.get("entry") is not None)
                return [r for r in got if r.get("entry") == first], "killer_claim_first_entry"
            return got, "killer_claim"
    t0, t1 = float(verdict["t_ms"]), float(verdict.get("t_last_ms") or verdict["t_ms"])
    first = [r for r in rows if float(r["t_ms"]) == t0 and int(r["slot"]) == int(verdict["slot"])]
    if not first:
        return [], "no_view"
    ent = first[0].get("entry")
    if ent is None:
        return first, "first_view"
    return ([r for r in rows if r.get("entry") == ent and t0 <= float(r["t_ms"]) <= t1],
            "reader_entry")


def kill_indices(verdicts: list[dict]) -> dict[str, dict]:
    """{death_id: {index, killer_side, counted, why}}: each verdict's kill
    index for its killer within its round, over the death stream."""
    out = {}
    rounds = defaultdict(list)
    for v in verdicts:
        rounds[v.get("round_no")].append(v)
    for rn, vs in rounds.items():
        count = Counter()
        unnamed = set()
        for v in sorted(vs, key=lambda v: (float(v["t_ms"]), int(v.get("slot") or 0))):
            side = v.get("side")
            ks = side if v.get("same_side") else OTHER.get(side)
            row = {"killer_side": ks, "round_no": rn}
            why = ("revive" if v.get("is_revive") else
                   "second_life" if v.get("is_second_life") else
                   "same_side" if v.get("same_side") else
                   "no_round" if rn is None else None)
            if why is not None:
                out[v["death_id"]] = {**row, "index": None, "counted": False, "why": why}
                continue
            if not v.get("killer") or ks is None:
                unnamed.add(ks)
                out[v["death_id"]] = {**row, "index": None, "counted": True,
                                      "why": "unnamed_killer"}
                continue
            key = (ks, v["killer"])
            count[key] += 1
            out[v["death_id"]] = {**row, "index": count[key], "counted": True,
                                  "why": "after_unnamed_killer" if ks in unnamed else None}
    return out


def witness(verdicts: list[dict], numeral_rows: list[dict]) -> list[dict]:
    """One check row per death verdict: the pooled numeral beside the death
    stream's kill index for its killer. `status` is `agree`, `disagree`,
    `unread` (no pooled numeral), or `not_scored` (an index the stream
    cannot give). `expected` is the numeral the index predicts ("" before
    `FIRST_DRAWN`).

    A reader entry bound by two verdicts witnesses neither: the death owner
    placed one of them on its neighbour's entry, and the numeral cannot say
    which. Both pool as `entry_shared`, naming the other verdict."""
    rows = [r for r in numeral_rows if r.get("kind", "numeral_observation") == "numeral_observation"]
    idx = kill_indices(verdicts)
    order = sorted(verdicts, key=lambda v: float(v["t_ms"]))
    binds = {v["death_id"]: bind_rows(v, rows) for v in order}
    owners = defaultdict(set)
    for did, (bound, _) in binds.items():
        for e in {r.get("entry") for r in bound} - {None}:
            owners[e].add(did)
    out = []
    for v in order:
        k = idx[v["death_id"]]
        bound, how = binds[v["death_id"]]
        pooled = pool_entry(bound)
        shared = sorted({d for r in bound if r.get("entry") is not None
                         for d in owners[r["entry"]]} - {v["death_id"]})
        if shared:
            pooled = {**pooled, "numeral": None, "reason": "entry_shared",
                      "shared_with": shared}
        row = {"death_id": v["death_id"], "round_no": v.get("round_no"),
               "t_ms": float(v["t_ms"]), "slot": v.get("slot"), "killer": v.get("killer"),
               "killer_side": k["killer_side"], "kill_index": k["index"],
               "index_note": k["why"], "binding": how, "numeral": pooled["numeral"],
               "pool": pooled,
               "rests_on": [{"stream": "death", "death_id": v["death_id"],
                             "version": v.get("death_adjudication_version")}]}
        expected = None
        if k["index"] is not None and k["why"] is None:
            expected = roman(k["index"]) if k["index"] >= FIRST_DRAWN else ""
        row["expected"] = expected
        if pooled["numeral"] is None:
            row["status"] = "unread"
        elif expected is None:
            row["status"] = "not_scored"
        elif pooled["numeral"] == expected:
            row["status"] = "agree"
        else:
            row["status"] = "disagree"
            got = ROMAN.get(pooled["numeral"])
            # A numeral above the stream's index: the stream missed a kill by
            # this killer earlier in the round, or names the wrong killer;
            # below it: the stream holds a false kill, or the wrong killer;
            # none where the index says one draws: a misread or a miss.
            kind = ("no_numeral" if got is None else
                    "numeral_above_index" if got > k["index"] else "numeral_below_index")
            row["surprise"] = {"kind": kind, "reader": pooled["numeral"],
                               "death_stream": expected,
                               "delta": None if got is None else got - k["index"]}
        out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    """Counts for a witness's rows: statuses, pooled reads by value, refusals
    by reason, and false reads (a numeral where the stream says kill 1 or 2)."""
    return {
        "status": dict(sorted(Counter(r["status"] for r in rows).items())),
        "read": dict(sorted(Counter(r["numeral"] or "(empty)" for r in rows
                                    if r["numeral"] is not None).items())),
        "refused": dict(sorted(Counter(r["pool"]["reason"] for r in rows
                                       if r["numeral"] is None).items())),
        "false_reads": sum(1 for r in rows if r["numeral"] and r["expected"] == ""),
        "missed_numerals": sum(1 for r in rows if r["numeral"] == "" and r["expected"]),
        "death_adjudication": DEATH_ADJUDICATION_VERSION,
    }


def events(session_id: str, rows: list[dict], numeral_version: str | None,
           death_version: str | None) -> list[dict]:
    """The `killstreak_witness` stream: a summary row, then one check row per
    death verdict."""
    common = {"session_id": session_id, "source": "killstreak_witness",
              "killstreak_witness_version": KILLSTREAK_WITNESS_VERSION,
              "inputs": {"killfeed_numeral": numeral_version, "death": death_version}}
    return ([{**common, "kind": "summary", **summary(rows)}]
            + [{**common, "kind": "killstreak_check", **r} for r in rows])
