r"""E1: can agreement conceal a wrong event history? A replay from storage.

    .\.venv\Scripts\python.exe prototypes\e1_agreement.py --replay
    .\.venv\Scripts\python.exe prototypes\e1_agreement.py --replay --session b3b9defb6fd7 --no-record

The first experiment of `docs/EXPERIMENT_PROGRAM.md`. Three channels count
the player's kills and deaths per round: the killfeed (`rounds.player_kills`,
`player_deaths`), the combat report (`adjudication.combat_report.round_verdicts`)
and the scoreboard (the outlined row's K and D, differenced across the round).
Agreement of those totals is the acceptance test the pipeline has used; this
runner asks whether a round whose totals agree can still hold a duplicate
beside a miss, or a death bound to the wrong witness, identity or life.

Decodes no video. Every input is a stored product at the stamp the ledger
entry `LEDGER_ID` (`e1-agreement-land-2026-09-28`) pins; a session whose stamps
differ is refused with the stamp named, never read. A channel whose stream is absent
is a missing channel, recorded as such per round, not a refusal.

`--replay` writes, under the store's `analysis/e1-agreement/`:

* `disagreements.json` -- every round where two available channels differ,
  with each channel's value and the STORED reason beside it: the report's
  `reason` where no panel was shown, the scoreboard's missing read, the
  round's second lives, the death rows' revives, plate refusals and statuses.
* `agreeing.json` -- the seeded rounds where all three channels agree, with
  every player kill and death bound to its source witness (the killfeed
  entry), its identity verdict (`adjudication.identity`, through the death
  row) and its life episode; the report's death panels bound to those deaths
  through `adjudication.combat_report.bind_deaths`; the report's KILLED rows'
  names beside the killfeed victims'; and what changes when a corroborating
  channel is withheld.
* `<session>.json` -- the per-session detail both lists are cut from.

A `--session` run writes the two lists as `disagreements.<suffix>.json` and
`agreeing.<suffix>.json`, so it never overwrites the corpus files: the
suffix is the session id for one session, else the count and a hash of the
sorted ids (the file lists them).

Withholding. The killfeed is the source of every event and cannot be
withheld from the event list; the corroborating channels can. The report
rows are named three times (`adjudication.combat_report.name_rows`): with
every witness, without the scoreboard, and without the killfeed portraits
and death bindings. The deaths are adjudicated twice more
(`adjudication.death.adjudicate_session_deaths`): on the stored scoreboard, a
control that must reproduce the stored verdicts, and without it
(`board_rows=[]`); each is compared with the stored verdicts. A verdict that
changes only without the scoreboard rested on it; one that does not rests
elsewhere.

Recorded as the `e1_agreement/replay` series through `reticle.metrics`, one
row per session and one for the corpus (session `pinned-18`). The evaluator's
duplicate-plus-miss check is tested on synthetic rounds in
`tests/test_e1_agreement.py`; those rounds are never counted as evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import metrics  # noqa: E402
from reticle.adjudication import combat_report as adj  # noqa: E402
from reticle.checks import KNOWN_KD, track_entries  # noqa: E402
from reticle.store import Store  # noqa: E402

TOOL = "e1_agreement"
VERSION = "e1-agreement-0.1.0"
LEDGER_ID = "e1-agreement-land-2026-09-28"
CORPUS_SESSION = "pinned-18"
#: A scoreboard read serves a round's boundary when it falls between the
#: previous round's close and this round's first possible kill
#: (`adjudication.combat_report.BUY_PHASE_MS`).
BUY_PHASE_MS = adj.BUY_PHASE_MS
#: Reads within one Tab hold vote on the boundary's value.
OPENING_GAP_MS = 3000.0

CHANNELS = ("killfeed", "report", "scoreboard")
THREE_WAY, TWO_WAY, DISAGREE, UNWITNESSED = "three_way", "two_way", "disagree", "unwitnessed"
#: The streams a session must hold for any replay: the event source and its rounds.
REQUIRED = ("hud", "death_adjudication")


# ------------------------------------------------------------------ inputs

def store_root() -> Path:
    return Store().root


def out_dir() -> Path:
    return store_root() / "analysis" / "e1-agreement"


def pinned_manifest() -> dict:
    """The ledger entry's pinned inputs: sessions and reader stamps."""
    path = store_root() / "notes" / "predictions.jsonl"
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        if row.get("id") == LEDGER_ID and row.get("kind") == "prediction":
            return row["pinned"]
    raise SystemExit(f"no ledger entry {LEDGER_ID} in {path}")


def rows_of(store: Store, kind: str, sid: str, row_kind: str) -> list[dict]:
    """The stored rows of one kind. `Store.read_events_kind` also returns the
    stream's first row for its stamp, whatever its kind; this drops it."""
    return [r for r in store.read_events_kind(kind, sid, row_kind) if r.get("kind") == row_kind]


def _date(store: Store, sid: str) -> str:
    from reticle.cli import _date_of
    return _date_of(store.read_manifest(sid))


def stamps(store: Store, sid: str, hud, death_rows: list[dict]) -> dict:
    """Each stream's stored stamp, or None where the stream is absent. The
    death stream stamps `death_adjudication_version` on every row, so it is
    read off a verdict row rather than through `events_version`."""
    hud_v = None
    if hud is not None and "hud_version" in hud.column_names and hud.num_rows:
        hud_v = hud.column("hud_version")[0].as_py()
    return {"hud": hud_v,
            "death_adjudication": death_rows[0].get("death_adjudication_version") if death_rows else None,
            "combat_report_round": store.events_version("combat_report_round", sid),
            "scoreboard": store.events_version("scoreboard", sid)}


def off_pinned(got: dict, pinned: dict) -> tuple[list[str], list[str]]:
    """(stale, missing): streams whose stored stamp is not the pinned one, and
    streams with no stamp at all, each named."""
    bad, missing = [], []
    for key, want in pinned.items():
        if key not in got:
            continue
        if got[key] is None:
            missing.append(key)
        elif got[key] != want:
            bad.append(f"{key} is {got[key]}, pinned {want}")
    return bad, missing


# ------------------------------------------------------------- the channels

def killfeed_rounds(rounds: list[dict]) -> dict[int, dict]:
    return {r["round_no"]: {"k": r.get("player_kills"), "d": r.get("player_deaths"),
                            "second_lives": r.get("player_second_lives"), "reason": None}
            for r in rounds}


def report_rounds(stream: list[dict], rounds: list[dict]) -> dict[int, dict]:
    """The report's per-round counts through its owner, or its refusal."""
    v = adj.round_verdicts(stream, rounds)
    if v["status"] != "ok":
        return {r["round_no"]: {"k": None, "d": None, "reason": v["reason"], "panels": []}
                for r in rounds}
    by_no = {r["round_no"]: r for r in stream if r.get("kind") == "round"}
    out = {}
    for no, rv in v["rounds"].items():
        raw = by_no[no]
        if rv["source"] == "combat_report":
            out[no] = {"k": rv["kills"], "d": rv["deaths"], "reason": None,
                       "panels": raw.get("panels") or []}
        else:
            out[no] = {"k": None, "d": None, "reason": raw.get("reason"), "panels": []}
    return out


def _mode(reads: list[dict], key: str) -> int | None:
    c = Counter(r[key] for r in reads if r.get(key) is not None)
    if not c:
        return None
    top = c.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


NO_SCOREBOARD = "no scoreboard stream stored"
NO_READ = "no player row read at the boundary"
SPLIT_READ = "the player row's reads at the boundary split their vote"


def boundaries(player_reads: list[dict] | None, rounds: list[dict]) -> list[dict]:
    """The outlined row's cumulative K and D at each round boundary.

    Boundary i (0-based) precedes round i: its window runs from the previous
    round's close to this round's first possible kill; the last boundary runs
    from the last round's close to the end. `player_reads` are the stored
    `row_observation` rows with `is_player`, sorted by time; None when the
    session has no scoreboard stream. Reads inside a window vote per field; a
    split vote or no read leaves the field None with the reason.
    """
    rs = sorted(rounds, key=lambda r: r["t_start_ms"])
    out = []
    for i in range(len(rs) + 1):
        lo = (rs[i - 1].get("t_close_ms") or rs[i - 1]["t_end_ms"]) if i else float("-inf")
        hi = rs[i]["t_start_ms"] + BUY_PHASE_MS if i < len(rs) else float("inf")
        b = {"index": i, "t_lo_ms": lo, "t_hi_ms": hi, "reads": 0, "k": None, "d": None, "reason": None}
        if player_reads is None:
            b["reason"] = NO_SCOREBOARD
        else:
            reads = [x for x in player_reads if lo <= x["t_ms"] <= hi]
            b["reads"] = len(reads)
            with_kd = [x for x in reads if x.get("kills") is not None and x.get("deaths") is not None]
            if not with_kd:
                b["reason"] = NO_READ
            else:
                b["k"], b["d"] = _mode(with_kd, "kills"), _mode(with_kd, "deaths")
                if b["k"] is None or b["d"] is None:
                    b["k"] = b["d"] = None
                    b["reason"] = SPLIT_READ
        out.append(b)
    return out


def scoreboard_rounds(bounds: list[dict], rounds: list[dict]) -> dict[int, dict]:
    """The outlined row's K and D differenced across each round: boundary i+1
    less boundary i, or None with the missing boundary's reason."""
    rs = sorted(rounds, key=lambda r: r["t_start_ms"])
    out = {}
    for i, r in enumerate(rs):
        a, z = bounds[i], bounds[i + 1]
        row = {"k": None, "d": None, "reason": None, "before_reads": a["reads"], "after_reads": z["reads"]}
        if a["k"] is None:
            row["reason"] = f"before: {a['reason']}"
        elif z["k"] is None:
            row["reason"] = f"after: {z['reason']}"
        else:
            row.update({"k": z["k"] - a["k"], "d": z["d"] - a["d"]})
        out[r["round_no"]] = row
    return out


def scoreboard_spans(bounds: list[dict], rounds: list[dict], kf: dict[int, dict],
                     rep: dict[int, dict]) -> list[dict]:
    """The scoreboard's increment between consecutive READ boundaries, over
    the rounds between them, beside the killfeed's and the report's sums.

    A span of one round is the per-round value; a longer span is what sparse
    Tab holds allow: the sum agrees or it does not, and a disagreement
    localises to the span, not a round. The report's sum exists only when
    every round in the span has a panel.
    """
    rs = sorted(rounds, key=lambda r: r["t_start_ms"])
    read = [b for b in bounds if b["k"] is not None]
    out = []
    for a, z in zip(read, read[1:]):
        nos = [rs[i]["round_no"] for i in range(a["index"], z["index"])]
        kf_k, kf_d = sum(kf[n]["k"] or 0 for n in nos), sum(kf[n]["d"] or 0 for n in nos)
        rep_ok = all(rep[n]["k"] is not None for n in nos)
        rep_k = sum(rep[n]["k"] for n in nos) if rep_ok else None
        rep_d = sum(rep[n]["d"] for n in nos) if rep_ok else None
        sb_k, sb_d = z["k"] - a["k"], z["d"] - a["d"]
        out.append({"rounds": nos, "scoreboard": {"k": sb_k, "d": sb_d},
                    "killfeed": {"k": kf_k, "d": kf_d}, "report": {"k": rep_k, "d": rep_d},
                    "agree_killfeed": (sb_k, sb_d) == (kf_k, kf_d),
                    "agree_report": None if not rep_ok else (sb_k, sb_d) == (rep_k, rep_d)})
    return out


# ------------------------------------------------------------- agreement

def classify(kf: dict, rep: dict, sb: dict) -> dict:
    """Which channels count this round, and which pairs differ.

    A pair differs when both have a value and either K or D differs. Three
    values with no differing pair is `three_way`; two is `two_way`; fewer
    than two values is `unwitnessed`; any differing pair is `disagree`.
    """
    vals = {"killfeed": kf, "report": rep, "scoreboard": sb}
    avail = [c for c in CHANNELS if vals[c]["k"] is not None and vals[c]["d"] is not None]
    differ = []
    for i, a in enumerate(avail):
        for b in avail[i + 1:]:
            for f in ("k", "d"):
                if vals[a][f] != vals[b][f]:
                    differ.append({"pair": [a, b], "field": f, a: vals[a][f], b: vals[b][f]})
    if differ:
        kind = DISAGREE
    elif len(avail) == 3:
        kind = THREE_WAY
    elif len(avail) == 2:
        kind = TWO_WAY
    else:
        kind = UNWITNESSED
    return {"kind": kind, "available": avail, "differ": differ}


def round_context(no: int, death_rows: list[dict]) -> dict:
    """What the stored death rows say about a round, beside its counts."""
    mine = [d for d in death_rows if d.get("round_no") == no]
    player = [d for d in mine if d.get("kf_player_kill") or d.get("kf_player_death")]
    return {"entries": len(mine), "player_entries": len(player),
            "revives": sum(bool(d.get("is_revive")) for d in mine),
            "player_second_lives": sum(bool(d.get("is_second_life")) for d in player
                                       if d.get("kf_player_death")),
            "victim_second_lives": sum(bool(d.get("is_second_life")) for d in player
                                       if d.get("kf_player_kill")),
            "plate_refusals": sorted({d["plate_refusal"] for d in mine if d.get("plate_refusal")}),
            "statuses": dict(Counter(d.get("status") for d in player)),
            "reasons": sorted({d["reason"] for d in player if d.get("reason")})}


# ------------------------------------------------------------- the seeded rounds

def life_episodes(player_events: list[dict]) -> dict[str, int]:
    """The life each of the player's entries falls in, by death id.

    A death ends a life unless it is a second life (Run It Back returns the
    player); a revive of the player starts the next one. Kills fall in the
    life current at their time.
    """
    life, out = 1, {}
    for d in sorted(player_events, key=lambda d: d["t_ms"]):
        out[d["death_id"]] = life
        if d.get("kf_player_death") and (d.get("is_revive") or not d.get("is_second_life")):
            life += 1
    return out


def _identity(d: dict, key: str) -> dict:
    v = (d.get("metadata") or {}).get(key) or {}
    return {"status": v.get("status", "none"), "agent": v.get("agent"),
            "p_named": v.get("p_named"), "channels": v.get("channels")}


def seed_round(no: int, death_rows: list[dict], panels: list[dict],
               verdict_by_entity: dict[str, dict]) -> dict:
    """Bind a round's player events to witness, identity and life, and set
    the report's panels beside them.

    `panels` are the round's panels after `adjudication.combat_report.name_rows`
    set `entity_id` and `death_entity` on their rows. A death panel whose
    KILLED YOU row carries no `death_entity` is an UNBOUND panel; a player
    death no death panel opened at, by the owner's window
    (`adjudication.combat_report.near_death`), is an UNPANELLED death. Either
    in a round whose totals agree is a duplicate beside a miss, and the round
    is flagged.
    """
    mine = [d for d in death_rows if d.get("round_no") == no and not d.get("is_revive")]
    revives = [d for d in death_rows if d.get("round_no") == no and d.get("is_revive")]
    player = [d for d in mine + revives if d.get("kf_player_kill") or d.get("kf_player_death")]
    life = life_episodes(player)
    bound = {row["death_entity"] for p in panels for row in p["rows"] if row.get("death_entity")}
    deaths, kills = [], []
    for d in sorted(mine, key=lambda d: d["t_ms"]):
        if d.get("kf_player_death"):
            deaths.append({"death_id": d["death_id"], "t_ms": d["t_ms"], "slot": d.get("slot"),
                           "life": life.get(d["death_id"]), "second_life": bool(d.get("is_second_life")),
                           "status": d.get("status"), "reason": d.get("reason"),
                           "channels": d.get("channels"), "witnesses": len(d.get("witnesses") or []),
                           "killer": _identity(d, "killer_identity"),
                           "weapon": (d.get("weapon_evidence") or {}).get("status"),
                           "report_bound": f"{d['death_id']}:killer" in bound})
        if d.get("kf_player_kill"):
            kills.append({"death_id": d["death_id"], "t_ms": d["t_ms"], "slot": d.get("slot"),
                          "life": life.get(d["death_id"]),
                          "victim_second_life": bool(d.get("is_second_life")),
                          "status": d.get("status"), "reason": d.get("reason"),
                          "channels": d.get("channels"), "witnesses": len(d.get("witnesses") or []),
                          "victim": _identity(d, "identity"),
                          "weapon": (d.get("weapon_evidence") or {}).get("status"),
                          "report_bound": d["death_id"] in bound})
    death_panels = [p for p in panels if p["kind"] == "death"]
    unbound = [p["start_ms"] for p in death_panels
               if any(r.get("killed_you") for r in p["rows"])
               and not any(r.get("death_entity") for r in p["rows"] if r.get("killed_you"))]
    real = [d for d in deaths if not d["second_life"]]
    unpanelled = [d["death_id"] for d in real
                  if not any(adj.near_death(p["start_ms"], d["t_ms"]) for p in death_panels)]
    # The report's KILLED rows, named by the arbiter, beside the killfeed victims.
    last = panels[-1] if panels else None
    report_names = []
    if last is not None:
        for row in last["rows"]:
            if row.get("killed") and not row.get("ally"):
                v = verdict_by_entity.get(row.get("entity_id")) or {}
                report_names.append(v.get("agent") if v.get("status") == "resolved" else None)
    kf_names = [k["victim"]["agent"] if k["victim"]["status"] == "resolved" else None for k in kills]
    named = None not in report_names and None not in kf_names
    names = {"report": report_names, "killfeed": kf_names,
             "agree": (sorted(report_names) == sorted(kf_names)) if named else None,
             "reason": None if named else "a KILLED row or a victim is unnamed"}
    return {"round_no": no, "deaths": deaths, "kills": kills,
            "panels": len(panels), "death_panels": len(death_panels),
            "unbound_panels": unbound, "unpanelled_deaths": unpanelled,
            "flag": bool(unbound or unpanelled) or names["agree"] is False,
            "names": names}


# ------------------------------------------------------------- withholding

def _verdict_map(verdicts: list[dict]) -> dict[str, dict]:
    return {v["entity_id"]: {"status": v["status"], "agent": v.get("agent")} for v in verdicts}


def name_report_rows(store: Store, sid: str, date: str, hud, rounds, death_times, lineup,
                     gallery, death_rows, *, board=None, portraits=None) -> tuple[list[dict], dict]:
    """Panels with their rows named, as `reticle combat-report` names them,
    with a corroborating channel withheld where the caller passes `[]`."""
    frames = [r for r in store.read_events("combat_report", sid) if r.get("kind") == "frame"]
    ps = adj.panels(frames, death_times)
    adj.assign_rounds(ps, rounds)
    t = hud.column("t_ms").to_pylist()
    tracks = lambda c: [x for x in track_entries(t, hud.column(f"kf_{c}_mask").to_pylist(),
                                                 hud.column(f"kf_{c}_wx").to_pylist())
                        if x["counted"]]
    if portraits is None:
        portraits = [o for o in store.read_events("killfeed_portrait", sid)
                     if o.get("kind") == "portrait_observation"]
    if board is None:
        board = [{"t": r["t_ms"], "agent": r.get("portrait_agent_best"),
                  "kills": r.get("kills"), "deaths": r.get("deaths")}
                 for r in rows_of(store, "scoreboard", sid, "row_observation")
                 if r.get("team") == "enemy" and r.get("portrait_agent_best")]
    claims, verdicts = adj.name_rows(sid, ps, rounds, tracks("kill"), tracks("death"),
                                     portraits, board, lineup["sides"]["enemy"], gallery,
                                     death_rows, lineup["sides"].get("ally", []),
                                     (lineup.get("player") or {}).get("agent"))
    return ps, _verdict_map(verdicts)


def compare_verdicts(full: dict[str, dict], held: dict[str, dict], entities: set[str]) -> dict:
    """How the withheld run's verdicts differ from the full run's on `entities`."""
    none = {"status": "none", "agent": None}
    changed, lost, gained, renamed = [], [], [], []
    for e in sorted(entities):
        a, b = full.get(e) or none, held.get(e) or none
        if a == b:
            continue
        changed.append({"entity_id": e, "full": a, "withheld": b})
        if a["status"] == "resolved" and b["status"] != "resolved":
            lost.append(e)
        elif a["status"] != "resolved" and b["status"] == "resolved":
            gained.append(e)
        elif a["status"] == b["status"] == "resolved":
            renamed.append(e)
    return {"entities": len(entities), "changed": len(changed), "lost": len(lost),
            "gained": len(gained), "renamed": len(renamed), "detail": changed}


def rerun_deaths(store: Store, sid: str, date: str, hud, rounds, lineup, gallery,
                 death_rows: list[dict], board_rows: list[dict]) -> dict:
    """The stored death verdicts against a rerun on `board_rows`: `[]` withholds
    the scoreboard; the stored scoreboard stream is the control, which must
    reproduce the stored verdicts before a withheld change means anything."""
    from reticle.adjudication.death import adjudicate_session_deaths, stored_second_life
    from reticle.adjudication.reliability import load as load_reliability
    from reticle.killfeed import (KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION,
                                  KILLFEED_WEAPON_VERSION)
    portraits = store.read_events("killfeed_portrait", sid)
    weapons = (store.read_events("killfeed_weapon", sid)
               if store.events_version("killfeed_weapon", sid) == KILLFEED_WEAPON_VERSION else None)
    names = (store.read_events("killfeed_name", sid)
             if store.events_version("killfeed_name", sid) == KILLFEED_NAME_VERSION else None)
    t0 = time.perf_counter()
    res = adjudicate_session_deaths(
        sid, rounds, hud, store.read_roster(sid, date), portraits, board_rows, lineup, gallery,
        source_version=KILLFEED_PORTRAIT_VERSION,
        second_life=stored_second_life(portraits, KILLFEED_PORTRAIT_VERSION),
        weapon_observations=weapons, name_observations=names,
        reliability=load_reliability(store.root))
    held = {}
    for r in res["rounds"]:
        for v in r["verdicts"]:
            d = v.to_dict()
            held[d["death_id"]] = d
    changed = []
    for d in death_rows:
        h = held.get(d["death_id"])
        if h is None:
            changed.append({"death_id": d["death_id"], "round_no": d.get("round_no"),
                            "player": bool(d.get("kf_player_kill") or d.get("kf_player_death")),
                            "change": "absent from the rerun"})
            continue
        diff = {}
        for key in ("status", "victim", "killer", "is_revive", "is_second_life"):
            if d.get(key) != h.get(key):
                diff[key] = [d.get(key), h.get(key)]
        for key in ("identity", "killer_identity"):
            a, b = _identity(d, key), _identity(h, key)
            if (a["status"], a["agent"]) != (b["status"], b["agent"]):
                diff[key] = [[a["status"], a["agent"]], [b["status"], b["agent"]]]
        if diff:
            changed.append({"death_id": d["death_id"], "round_no": d.get("round_no"),
                            "player": bool(d.get("kf_player_kill") or d.get("kf_player_death")),
                            "change": diff})
    return {"deaths": len(death_rows), "rerun_deaths": len(held), "passes": res.get("passes"),
            "seconds": round(time.perf_counter() - t0, 1), "changed": len(changed),
            "player_changed": sum(c.get("player", False) for c in changed), "detail": changed}


# ------------------------------------------------------------- one session

def replay_session(store: Store, sid: str, pinned: dict, *, withhold: bool = True) -> dict:
    from reticle.adjudication.identity import load_identity_gallery
    from reticle.lineup import load_lineup
    from reticle.rounds import player_death_times
    date = _date(store, sid)
    hud = store.read_hud(sid, date) if store.hud_path(sid, date).is_file() else None
    death_rows = rows_of(store, "death", sid, "death_verdict")
    got = stamps(store, sid, hud, death_rows)
    out = {"session": sid, "version": VERSION, "stamps": got, "refused": None}
    bad, missing = off_pinned(got, pinned["readers"])
    out["missing"] = missing
    if bad:
        out["refused"] = "; ".join(bad)
        return out
    rounds_tbl = store.read_rounds(sid, date)
    if any(k in missing for k in REQUIRED) or rounds_tbl is None:
        absent = missing + ([] if rounds_tbl is not None else ["rounds"])
        out["refused"] = "no stored " + ", ".join(absent)
        return out
    rounds = sorted(rounds_tbl.to_pylist(), key=lambda r: r["t_start_ms"])
    report_stream = store.read_events_kind("combat_report_round", sid, "round")
    player_reads = None
    if "scoreboard" not in missing:
        player_reads = sorted((r for r in rows_of(store, "scoreboard", sid, "row_observation")
                               if r.get("is_player")), key=lambda r: r["t_ms"])
    kf = killfeed_rounds(rounds)
    rep = report_rounds(report_stream, rounds)
    bounds = boundaries(player_reads, rounds)
    sb = scoreboard_rounds(bounds, rounds)
    out["boundaries"] = bounds
    out["spans"] = scoreboard_spans(bounds, rounds, kf, rep)
    per_round = []
    for r in rounds:
        no = r["round_no"]
        c = classify(kf[no], rep[no], sb[no])
        per_round.append({"round_no": no, "t_start_ms": r["t_start_ms"], "t_end_ms": r["t_end_ms"],
                          "killfeed": kf[no], "report": rep[no], "scoreboard": sb[no],
                          **c, "context": round_context(no, death_rows)})
    out["rounds"] = per_round
    out["round_version"] = rounds[0].get("round_version") if rounds else None
    out["player_reads"] = None if player_reads is None else len(player_reads)
    out["player_reads_with_kd"] = None if player_reads is None else sum(
        r.get("kills") is not None and r.get("deaths") is not None for r in player_reads)
    known = KNOWN_KD.get(sid)
    out["known_kd"] = list(known) if known else None
    seeded_nos = [x["round_no"] for x in per_round if x["kind"] == THREE_WAY]
    out["seeded"], out["withheld"] = [], {}
    lineup = load_lineup(sid, store.root)
    if not (lineup and lineup.get("sides", {}).get("enemy")):
        out["seed_refused"] = "no stored lineup with an enemy side; report rows cannot be named"
        return out
    gallery = load_identity_gallery(store.root)
    death_times = player_death_times(hud)
    ps, full = name_report_rows(store, sid, date, hud, rounds, death_times, lineup, gallery, death_rows)
    for no in seeded_nos:
        out["seeded"].append(seed_round(no, death_rows, [p for p in ps if p.get("round_no") == no], full))
    if withhold and seeded_nos:
        entities = {row["entity_id"] for p in ps if p.get("round_no") in seeded_nos
                    for row in p["rows"] if row.get("entity_id")}
        _, no_board = name_report_rows(store, sid, date, hud, rounds, death_times, lineup, gallery,
                                       death_rows, board=[])
        _, no_kf = name_report_rows(store, sid, date, hud, rounds, death_times, lineup, gallery,
                                    [], portraits=[])
        rerun = lambda board: rerun_deaths(store, sid, date, hud, rounds, lineup, gallery,
                                           death_rows, board)
        out["withheld"] = {"report_rows_without_scoreboard": compare_verdicts(full, no_board, entities),
                           "report_rows_without_killfeed": compare_verdicts(full, no_kf, entities),
                           "deaths_rerun_control": rerun(store.read_events("scoreboard", sid)),
                           "deaths_without_scoreboard": rerun([])}
    return out


# ------------------------------------------------------------- summaries

def summarise(res: dict) -> dict:
    """The numbers one session's replay records, and the reasons beside them."""
    if res.get("refused"):
        return {"refused": 1, "reasons": {}}
    rounds = res["rounds"]
    kinds = Counter(r["kind"] for r in rounds)
    reasons = Counter()
    for r in rounds:
        if r["kind"] != DISAGREE:
            continue
        for c in ("report", "scoreboard"):
            if r[c]["reason"]:
                reasons[f"{c}: {r[c]['reason']}"] += 1
        if r["context"]["player_second_lives"] or r["context"]["victim_second_lives"]:
            reasons["killfeed: a second life in the round"] += 1
        if r["context"]["revives"]:
            reasons["killfeed: a revive in the round"] += 1
    pairs = Counter(f"{d['pair'][0]}-{d['pair'][1]}" for r in rounds for d in r["differ"])
    seeded = res.get("seeded", [])
    vals = {"rounds": len(rounds), "three_way": kinds[THREE_WAY], "two_way": kinds[TWO_WAY],
            "disagree": kinds[DISAGREE], "unwitnessed": kinds[UNWITNESSED],
            "differ_killfeed_report": pairs["killfeed-report"],
            "differ_killfeed_scoreboard": pairs["killfeed-scoreboard"],
            "differ_report_scoreboard": pairs["report-scoreboard"],
            "disagree_no_panel": sum(v for k, v in reasons.items() if k.startswith("report: no panel")),
            "disagree_no_scoreboard_read": sum(v for k, v in reasons.items()
                                               if k.startswith("scoreboard: ")
                                               and not k.endswith(NO_SCOREBOARD)),
            "disagree_no_scoreboard_stream": sum(v for k, v in reasons.items()
                                                 if k.endswith(NO_SCOREBOARD)),
            "disagree_second_life": reasons["killfeed: a second life in the round"],
            "disagree_revive": reasons["killfeed: a revive in the round"],
            "player_reads": res.get("player_reads") or 0,
            "player_reads_with_kd": res.get("player_reads_with_kd") or 0,
            "boundaries": len(res.get("boundaries", [])),
            "boundaries_read": sum(b["k"] is not None for b in res.get("boundaries", [])),
            "spans": len(res.get("spans", [])),
            "span_rounds": sum(len(s["rounds"]) for s in res.get("spans", [])),
            "spans_agree_killfeed": sum(s["agree_killfeed"] for s in res.get("spans", [])),
            "spans_disagree_killfeed": sum(not s["agree_killfeed"] for s in res.get("spans", [])),
            "spans_agree_report": sum(s["agree_report"] is True for s in res.get("spans", [])),
            "spans_disagree_report": sum(s["agree_report"] is False for s in res.get("spans", [])),
            "seeded": len(seeded),
            "seeded_deaths": sum(len(s["deaths"]) for s in seeded),
            "seeded_kills": sum(len(s["kills"]) for s in seeded),
            "deaths_report_bound": sum(d["report_bound"] for s in seeded for d in s["deaths"]),
            "kills_report_bound": sum(k["report_bound"] for s in seeded for k in s["kills"]),
            "deaths_killer_named": sum(d["killer"]["status"] == "resolved" for s in seeded for d in s["deaths"]),
            "kills_victim_named": sum(k["victim"]["status"] == "resolved" for s in seeded for k in s["kills"]),
            "unbound_panels": sum(len(s["unbound_panels"]) for s in seeded),
            "unpanelled_deaths": sum(len(s["unpanelled_deaths"]) for s in seeded),
            "names_agree": sum(s["names"]["agree"] is True for s in seeded),
            "names_disagree": sum(s["names"]["agree"] is False for s in seeded),
            "names_unnamed": sum(s["names"]["agree"] is None for s in seeded),
            "flagged": sum(s["flag"] for s in seeded)}
    w = res.get("withheld") or {}
    for key, short in (("report_rows_without_scoreboard", "rows_no_scoreboard"),
                       ("report_rows_without_killfeed", "rows_no_killfeed")):
        if key in w:
            vals[f"{short}_entities"] = w[key]["entities"]
            vals[f"{short}_changed"] = w[key]["changed"]
            vals[f"{short}_lost"] = w[key]["lost"]
            vals[f"{short}_renamed"] = w[key]["renamed"]
    if "deaths_without_scoreboard" in w:
        d, c = w["deaths_without_scoreboard"], w["deaths_rerun_control"]
        vals["deaths_no_scoreboard_changed"] = d["changed"]
        vals["deaths_no_scoreboard_player_changed"] = d["player_changed"]
        vals["deaths_control_changed"] = c["changed"]
        vals["deaths_control_player_changed"] = c["player_changed"]
        vals["deaths_rerun_seconds"] = round(d["seconds"] + c["seconds"], 1)
    known = res.get("known_kd")
    if known:
        kv = sum((r["report"]["k"] if r["report"]["k"] is not None else r["killfeed"]["k"]) or 0
                 for r in rounds)
        dv = sum((r["report"]["d"] if r["report"]["d"] is not None else r["killfeed"]["d"]) or 0
                 for r in rounds)
        vals["verdict_minus_known_k"] = kv - known[0]
        vals["verdict_minus_known_d"] = dv - known[1]
        # The corpus row sums sessions; signed deltas of opposite sign cancel there.
        vals["verdict_abs_minus_known_k"] = abs(kv - known[0])
        vals["verdict_abs_minus_known_d"] = abs(dv - known[1])
        vals["verdict_sessions_off_known"] = int((kv, dv) != tuple(known))
    vals["reasons"] = dict(reasons)
    return vals


def disagreement_rows(res: dict) -> list[dict]:
    return [{"session": res["session"], **{k: r[k] for k in
             ("round_no", "t_start_ms", "t_end_ms", "killfeed", "report", "scoreboard",
              "available", "differ", "context")}}
            for r in res.get("rounds", []) if r["kind"] == DISAGREE]


def agreeing_rows(res: dict) -> list[dict]:
    return [{"session": res["session"], **s} for s in res.get("seeded", [])]


def _numbers(vals: dict) -> dict:
    return {k: v for k, v in vals.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


# ------------------------------------------------------------- main

def replay(sessions: list[str] | None, *, record: bool, withhold: bool) -> int:
    store = Store()
    pinned = pinned_manifest()
    sids = sessions or pinned["sessions"]
    unknown = [s for s in sids if s not in pinned["sessions"]]
    if unknown:
        raise SystemExit(f"not pinned by {LEDGER_ID}: {unknown}")
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    deps = {"version": VERSION, "readers": pinned["readers"], "corpus": pinned["corpus"]}
    disagreements, agreeing, corpus, reasons = [], [], Counter(), Counter()
    refused = {}
    for sid in sids:
        t0 = time.perf_counter()
        res = replay_session(store, sid, pinned, withhold=withhold)
        (out / f"{sid}.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
        vals = summarise(res)
        if res.get("refused"):
            refused[sid] = res["refused"]
            print(f"{sid}: REFUSED {res['refused']}", flush=True)
            continue
        disagreements += disagreement_rows(res)
        disagreements += [{"session": sid, "span": True, **s} for s in res.get("spans", [])
                          if not s["agree_killfeed"] or s["agree_report"] is False]
        agreeing += agreeing_rows(res)
        corpus.update(_numbers(vals))
        reasons.update(vals["reasons"])
        secs = time.perf_counter() - t0
        print(f"{sid}: rounds {vals['rounds']} three-way {vals['three_way']} two-way {vals['two_way']} "
              f"disagree {vals['disagree']} unwitnessed {vals['unwitnessed']}; seeded deaths "
              f"{vals['seeded_deaths']} kills {vals['seeded_kills']}; flagged {vals['flagged']}; "
              f"missing {res['missing'] or 'none'}; {secs:.0f}s", flush=True)
        for r in res["rounds"]:
            if r["kind"] == DISAGREE:
                print(f"    round {r['round_no']:>2}: kf {r['killfeed']['k']}/{r['killfeed']['d']}  "
                      f"report {r['report']['k']}/{r['report']['d']}  board {r['scoreboard']['k']}/"
                      f"{r['scoreboard']['d']}  {r['report']['reason'] or r['scoreboard']['reason'] or ''}")
        for s in res.get("seeded", []):
            if s["flag"]:
                print(f"    FLAG round {s['round_no']}: unbound panels {s['unbound_panels']} "
                      f"unpanelled {s['unpanelled_deaths']} names {s['names']}")
        if record:
            metrics.record(TOOL, part="replay", session=sid, values=_numbers(vals), deps=deps,
                           context={"round_version": res.get("round_version"),
                                    "player_reads": res.get("player_reads"),
                                    "missing": res.get("missing"), "withhold": withhold},
                           note="E1 replay from storage: three channels' per-round K/D, the seeded "
                                "agreeing rounds bound to witness, identity and life, channels withheld")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    suffix = "" if not sessions else f".{sessions[0]}" if len(sessions) == 1 else (
        f".{len(sessions)}-sessions-"
        + hashlib.sha1(",".join(sorted(sessions)).encode()).hexdigest()[:8])
    for name, rows in (("disagreements", disagreements), ("agreeing", agreeing)):
        (out / f"{name}{suffix}.json").write_text(
            json.dumps({"version": VERSION, "at": stamp, "ledger": LEDGER_ID, "sessions": sids,
                        "refused": refused, "reasons": dict(reasons), "rows": rows},
                       indent=1, default=float), encoding="utf-8")
    print(f"corpus: {json.dumps(dict(corpus))}")
    for k, v in sorted(reasons.items()):
        print(f"  {k}: {v}")
    if refused:
        print(f"refused: {refused}")
    if record and not sessions:
        metrics.record(TOOL, part="replay", session=CORPUS_SESSION,
                       values={**dict(corpus), "sessions": len(sids), "refused": len(refused)},
                       deps=deps, context={"sessions": sids, "refused": refused,
                                           "reasons": dict(reasons), "withhold": withhold},
                       note="E1 replay over the pinned corpus; per-session rows carry the detail")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument("--replay", action="store_true", help="replay the pinned sessions from storage")
    ap.add_argument("--session", action="append", help="one pinned session (repeatable)")
    ap.add_argument("--no-record", action="store_true", help="do not record the metric")
    ap.add_argument("--no-withhold", action="store_true", help="skip the withholding reruns")
    args = ap.parse_args(argv)
    if not args.replay:
        ap.error("--replay is the only step")
    return replay(args.session, record=not args.no_record, withhold=not args.no_withhold)


if __name__ == "__main__":
    sys.exit(main())
