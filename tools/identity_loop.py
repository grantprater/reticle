"""Session-wide death identity with this session's own labelled portraits.

    .\\.venv\\Scripts\\python.exe tools/identity_loop.py [--session SID] [--out FILE]

Pass 0 adjudicates every round's deaths as `death_round4_review` does: stored
killfeed portraits against the official art, then the scoreboard's dimmed
rows, gated on the roster. `adjudication.death.portrait_exemplars` then takes
the portraits of every death a NON-portrait witness named independently (a
single scoreboard binding, or the player HUD) and pass 1 scores every portrait
against the official art plus those exemplars, never an entry's own. A name an
exemplar decided carries `depends_on` on the death that labelled it, so the
arbiter never counts it as independent.

Elimination names and exemplar-decided names never become exemplars, so the
labels cannot feed on themselves; the loop stops when the exemplar set stops
changing. Stored data only: nothing here decodes video.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.adjudication.death import (DEATH_ADJUDICATION_VERSION,
    adjudicate_round_deaths, attach_stored_killfeed_portraits, portrait_exemplars,
    scoreboard_death_claims)
from reticle.adjudication.identity import AGENT_IDENTITY_VERSION, load_identity_gallery
from reticle.adjudication.scoreboard import scoreboard_openings
from reticle.cli import _date_of
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION
from reticle.lineup import load_lineup
from reticle.reconciliation import audit_board_alive, contradicted_openings
from reticle.store import Store
from prototypes.round_identity_eval import extract_round_killfeed_entries, load_round_bounds

MAX_PASSES = 4


def rounds_of(store, session, date, hud):
    out, n = [], 1
    while True:
        try:
            start, end, _ = load_round_bounds(store, session, date, n)
        except ValueError:
            return out
        entries, seen, dropped = [], set(), Counter()
        for e in extract_round_killfeed_entries(hud, start, end):
            key = (float(e["t_ms"]), e.get("side"), e.get("slot"))
            if key in seen:
                dropped["duplicate_entry"] += 1
                continue
            seen.add(key)
            for k in ("claim", "v_comps", "k_comps", "location", "killer_location"):
                e[k] = None
            entries.append(e)
        out.append({"round": n, "start": start, "end": end, "entries": entries,
                    "dropped": dict(dropped)})
        n += 1


def run_pass(rounds, portraits, lineup, gallery, roster, hud_table, roster_table,
             board_rows, player_agent, exemplars):
    results = []
    for r in rounds:
        entries = attach_stored_killfeed_portraits(
            r["entries"], portraits, lineup, gallery,
            source_version=KILLFEED_PORTRAIT_VERSION, exemplars=exemplars)
        window = [row for row in roster if r["start"] <= row["t_ms"] <= r["end"]]
        first = adjudicate_round_deaths("S", entries, window, player_agent=player_agent)
        openings = scoreboard_openings([row for row in board_rows
                                        if r["start"] <= float(row.get("t_ms", -1)) <= r["end"]])
        audit = audit_board_alive(openings, hud_table, roster_table)
        board = scoreboard_death_claims(
            entries, openings, {i: v.victim for i, v in enumerate(first)},
            {i for i, v in enumerate(first) if v.is_second_life},
            contradicted_openings(audit))
        verdicts = adjudicate_round_deaths("S", entries, window, player_agent=player_agent,
                                           scoreboard_claims=board)
        results.append({"round": r["round"], "entries": entries, "verdicts": verdicts})
    return results


def summarize(results):
    c = Counter()
    rows = []
    for r in results:
        for e, v in zip(r["entries"], r["verdicts"]):
            vi, ki = v.metadata.get("identity") or {}, v.metadata.get("killer_identity") or {}
            c["deaths"] += 1
            c[f"victim_{vi.get('status', 'none')}"] += 1
            c[f"killer_{ki.get('status', 'none')}"] += 1
            if v.victim and not vi.get("independent_channels"):
                c["victim_named_dependent_only"] += 1
            rows.append({"round": r["round"], "t_ms": float(e["t_ms"]), "side": e.get("side"),
                         "slot": e.get("slot"), "victim": v.victim, "killer": v.killer,
                         "victim_status": vi.get("status"), "killer_status": ki.get("status"),
                         "victim_channels": vi.get("channels"),
                         "killer_channels": ki.get("channels"),
                         "victim_depends_on": sorted({d for cl in vi.get("claims", [])
                                                      for d in cl.get("depends_on", [])}),
                         "killer_depends_on": sorted({d for cl in ki.get("claims", [])
                                                      for d in cl.get("depends_on", [])}),
                         "victim_reason": vi.get("reason"), "killer_reason": ki.get("reason")})
    return dict(c), rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="a06f04a0059f")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    store = Store()
    manifest = store.read_manifest(args.session)
    date = _date_of(manifest)
    hud_table, roster_table = store.read_hud(args.session, date), store.read_roster(args.session, date)
    lineup = load_lineup(args.session, store.root)
    player_agent = (lineup.get("player") or {}).get("agent")
    portraits = store.read_events("killfeed_portrait", args.session)
    board_rows = store.read_events("scoreboard", args.session)
    gallery = load_identity_gallery(store.root)
    rounds = rounds_of(store, args.session, date, hud_table.to_pydict())
    roster = roster_table.to_pylist()

    passes, exemplars, keys = [], [], None
    for n in range(MAX_PASSES):
        results = run_pass(rounds, portraits, lineup, gallery, roster, hud_table,
                           roster_table, board_rows, player_agent, exemplars)
        counts, rows = summarize(results)
        harvested = portrait_exemplars(
            [v for r in results for v in r["verdicts"]],
            [e for r in results for e in r["entries"]])
        passes.append({"pass": n, "exemplars_in": len(exemplars), "counts": counts, "deaths": rows,
                       "exemplar_labels": Counter(f"{x['role']}:{x['agent']}:{x['label_channel']}"
                                                  for x in harvested)})
        new_keys = {x["observation_key"] for x in harvested}
        if new_keys == keys:
            break
        keys, exemplars = new_keys, harvested

    report = {"session": args.session, "player_agent": player_agent,
              "board": {s: b.get("agents") for s, b in (lineup.get("board") or {}).items()},
              "dropped": {r["round"]: r["dropped"] for r in rounds if r["dropped"]},
              "versions": {"death_adjudication": DEATH_ADJUDICATION_VERSION,
                           "agent_identity": AGENT_IDENTITY_VERSION,
                           "killfeed_portrait": store.events_version("killfeed_portrait", args.session),
                           "scoreboard": store.events_version("scoreboard", args.session),
                           "lineup": lineup.get("version")},
              "passes": passes}
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    for p in passes:
        print(p["pass"], "exemplars", p["exemplars_in"], p["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
