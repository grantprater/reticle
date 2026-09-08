"""Generate the perishable half of CLAUDE.md from the store, so it cannot rot.

    .\\.venv\\Scripts\\python.exe -m reticle.status
    .\\.venv\\Scripts\\python.exe -m reticle.status --write        # -> STATUS.md

Why this exists
---------------
Measured 2026-08-27: CLAUDE.md is 83 KB and **28.8 KB of it is status carrying
77 numeric claims** -- the largest category in the file, the fastest-rotting,
and the one loaded eagerly every session whether or not it is relevant. Every
one of those numbers is a snapshot that goes stale silently, which is the same
failure that left a convention describing a practice the repo had abandoned.

The fix is not better prose. **A fact that is computed cannot disagree with the
code**, so status is generated rather than written, and CLAUDE.md keeps a
pointer instead of a copy. That is the same two-tier move that already works for
`prototypes/CLAUDE.md`: push everything to the laziest tier that still prevents
the mistake.

What stays prose, deliberately
------------------------------
**Handoff INTENT** -- "next session do X, because Y". the framing, and the player is
right that it is a special case: it is a decision rather than a fact, nothing in
the store implies it, and regenerating it would be inventing it. Roughly 2-3 KB
of the 20 KB "Picking up" section is really this; the rest is derivable and
lives here now.

Everything below is read from the store at run time. If a number here is wrong,
the store is wrong -- there is no third possibility, which is the entire point.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from . import geometry
from .checks import KNOWN_KD, player_events
from .store import DEFAULT_STORE, Store
from .version import HUD_VERSION, MINIMAP_VERSION, PING_VERSION, ROSTER_VERSION

LABEL_KINDS = ("minimap", "minimap_dynamic", "minimap_agent", "enemies", "map_mask")


def _date_of(man: dict) -> str:
    return (man.get("ingested_at") or "")[:10]


def _has_geometry(sid: str, root) -> bool:
    """Does this session reach a BUILT geometry npz?

    Two ways to answer no and the column shows one `-` for both: the session
    has no `map:` tag, or its `<map>__<profile>` key has never been built.
    `doctor`'s COVERAGE check is what separates them.
    """
    p = geometry.path_of(sid, root)
    return p is not None and p.is_file()


def _map_of(man: dict) -> str:
    return next((t.split(":", 1)[1] for t in man.get("tags", []) if t.startswith("map:")), "?")


def _has(root: Path, *parts: str) -> bool:
    return any(root.joinpath(*parts).parent.glob(parts[-1])) if parts else False


def stored_versions(root: Path) -> dict[str, collections.Counter]:
    """What version each L1 table was ACTUALLY written at.

    This line of the report used to print `version.HUD_VERSION` -- the version
    the code would produce if you re-ran it, not the one in the store. It is a
    tempting mistake because the header of the generated file says *a fact that
    is computed cannot disagree with the code*, and this one could not: it WAS
    the code, and never opened the store at all.

    It went wrong the moment a version was bumped. On 2026-09-05 the report read
    `store hud-0.10.0` while all 17 tables in it were `hud-0.9.0` and the three
    minimap tables were a version behind as well -- and the one number whose job
    is to say what the store contains was the one saying otherwise.

    The same paragraph in prototypes/CLAUDE.md records the hand-written version
    of this exact error (*the store is at hud-0.8.1 throughout* against 0.9.0),
    which is what motivated generating the report. Generating it fixed the
    staleness and kept the wrong source.
    """
    import pyarrow.parquet as pq

    out: dict[str, collections.Counter] = {}
    for kind, fname, key in (("hud", "hud.parquet", b"hud_version"),
                             ("minimap", "minimap.parquet", b"minimap_version"),
                             ("roster", "roster.parquet", b"roster_version")):
        c: collections.Counter = collections.Counter()
        d = root / "l1" / kind
        if d.is_dir():
            for f in d.rglob(fname):
                try:
                    md = pq.read_schema(f).metadata or {}
                except Exception:
                    c["unreadable"] += 1
                    continue
                c[md.get(key, b"?").decode()] += 1
        out[kind] = c

    # Events are not parquet and were invisible here, which is half of why
    # `PING_VERSION` could be written by every row and read by nothing. A
    # store holding pings at two definitions now says so.
    c = collections.Counter()
    d = root / "events" / "ping"
    if d.is_dir():
        for f in sorted(d.glob("*.jsonl")):
            v = None
            try:
                for ln in f.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        v = json.loads(ln).get("ping_version")
                        break
            except Exception:
                v = "unreadable"
            c[v or "(no rows)"] += 1
    out["ping"] = c
    return out


def collect(store: Store) -> dict:
    """Everything the status report needs, read once."""
    root = store.root
    out = {"sessions": [], "store": str(root),
           "hud_version": HUD_VERSION,
           "minimap_version": MINIMAP_VERSION,
           "ping_version": PING_VERSION,
           "roster_version": ROSTER_VERSION,
           "stored": {k: dict(v) for k, v in stored_versions(root).items()}}
    label_rows: dict = collections.defaultdict(dict)
    for kind in LABEL_KINDS:
        d = root / "labels" / kind
        if not d.is_dir():
            continue
        for p in d.glob("*.jsonl"):
            sid = p.stem.split(".")[0]
            rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            last = {}
            for r in rows:
                key = (r.get("t_ms"), r.get("x"), r.get("y"))
                last[key] = r
            label_rows[sid][kind] = len(last)
        for p in d.glob("*.png"):
            label_rows[p.stem.split(".")[0]].setdefault(kind, 0)
            label_rows[p.stem.split(".")[0]][kind] = "painted"

    for man in sorted(store.sessions(), key=lambda m: m["source"]["filename"]):
        sid = man["session_id"]
        date = _date_of(man)
        src = man["source"]
        rec = {
            "sid": sid, "map": _map_of(man), "date": date,
            "file": src["filename"], "minutes": src["duration_ms"] / 60000.0,
            "profile": man.get("source_profile", "?"),
            "hud": store.hud_path(sid, date).is_file(),
            "primitives": store.primitives_path(sid, date).is_file(),
            "spans": store.spans_path(sid, date).is_file(),
            "rounds": store.rounds_path(sid, date).is_file(),
            "geometry": _has_geometry(sid, root),
            "known": KNOWN_KD.get(sid),
            "labels": dict(label_rows.get(sid, {})),
        }
        # Rounds are cheap and recomputed rather than trusted: the parquet may
        # predate a change to rounds.py, and a stale table is exactly what this
        # module exists to make impossible.
        rec["n_rounds"] = rec["won"] = rec["lost"] = rec["planted"] = None
        rec["kills"] = rec["deaths"] = None
        if rec["hud"]:
            try:
                import pyarrow.parquet as pq

                from .rounds import build_rounds
                rs = build_rounds(pq.read_table(store.hud_path(sid, date)))
                if rs:
                    rec["n_rounds"] = len(rs)
                    # `is True` / `is False`, not truthiness: an unresolved
                    # side leaves `won` NULL, and `len(rs) - won` would book
                    # every one of those as a loss. `cmd_rounds` already
                    # excludes nulls and this disagreed with it -- the wrong
                    # one being the half that generates STATUS.md.
                    rec["won"] = sum(1 for r in rs if r["won"] is True)
                    rec["lost"] = sum(1 for r in rs if r["won"] is False)
                    rec["planted"] = sum(1 for r in rs if r["spike_planted"])
                    # Per-round sums, kept because the GAP between these and
                    # the session totals below is itself a measurement: it is
                    # the events that fall outside any detected round.
                    rec["round_kills"] = sum(r["player_kills"] for r in rs)
                    rec["round_deaths"] = sum(r["player_deaths"] for r in rs)
                # **Score against the SESSION total, not the per-round sum.**
                # `checks.KNOWN_KD` comes off the end-of-match scoreboard, which
                # counts every event in the match; a per-round sum silently
                # drops any event the round detector could not attribute, and a
                # round the scoreline was unreadable across is merged into its
                # neighbour. Measured 2026-09-05 over 17 sessions: per-round
                # scores 10 exact, session totals score 12 -- and the two it
                # differs on (5822b6646448, b7d24102a6f6) are events TODAY'S
                # killfeed fixes recovered, which the round attribution then
                # dropped again. Comparing a partial count against a total is
                # not a comparison.
                tbl = pq.read_table(store.hud_path(sid, date))
                ev = player_events(
                    tbl.column("t_ms").to_pylist(),
                    tbl.column("kf_kill_mask").to_pylist(),
                    tbl.column("kf_death_mask").to_pylist(),
                    [int(x) for x in tbl.column("kf_kill_wx").to_pylist()],
                    [int(x) for x in tbl.column("kf_death_wx").to_pylist()],
                )
                rec["kills"], rec["deaths"] = ev["kills"], ev["deaths"]
            except Exception as e:                      # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
        out["sessions"].append(rec)
    return out


def render(data: dict, markdown: bool = False) -> str:
    ss = data["sessions"]
    L: list[str] = []
    h = "## Pipeline status (generated)" if markdown else "PIPELINE STATUS"
    L.append(h)
    L.append("")
    if markdown:
        L.append("*Generated by `reticle status --write`. Do not edit: a fact that is")
        L.append("computed cannot disagree with the code. Handoff INTENT is not here --")
        L.append("that is a decision, not a fact, and stays in CLAUDE.md by hand.*")
        L.append("")
    scored = [s for s in ss if s["known"] and s["kills"] is not None]
    exact = [s for s in scored
             if (s["kills"], s["deaths"]) == (s["known"][0], s["known"][1])]
    L.append(f"{len(ss)} sessions ingested, "
             f"{sum(s['n_rounds'] or 0 for s in ss)} rounds derived.")
    for kind, code_v in (("hud", data["hud_version"]),
                         ("minimap", data["minimap_version"]),
                         # events, not a table -- but a version stamp nothing
                         # reports is a version stamp nothing can act on
                         ("ping", data["ping_version"]),
                         ("roster", data["roster_version"])):
        got = data.get("stored", {}).get(kind, {})
        if not got:
            continue
        parts = ", ".join(f"{n} at `{v}`" for v, n in sorted(got.items()))
        stale = sum(n for v, n in got.items() if v != code_v)
        line = f"L1 {kind}: {parts}; code is at `{code_v}`"
        if stale:
            line += f" -- **{stale} STALE**, re-read with `reticle scan`"
        L.append(line)
    if scored:
        L.append(f"{len(exact)} of {len(scored)} exact against `checks.KNOWN_KD`.")
    planted = [s for s in ss if s["planted"] is not None and s["n_rounds"]]
    if planted:
        tp = sum(s["planted"] for s in planted)
        tr = sum(s["n_rounds"] for s in planted)
        L.append(f"Plants: {tp}/{tr} rounds ({tp / tr:.0%}).")
    L.append("")

    cols = ("session", "map", "min", "rnds", "W-L", "plant", "K/D", "known", "d",
            "geo", "labels")
    rows = []
    for s in ss:
        kd = f"{s['kills']}/{s['deaths']}" if s["kills"] is not None else "--"
        kn = f"{s['known'][0]}/{s['known'][1]}" if s["known"] else "--"
        if s["known"] and s["kills"] is not None:
            dk, dd = s["kills"] - s["known"][0], s["deaths"] - s["known"][1]
            delta = "exact" if (dk, dd) == (0, 0) else f"{dk:+d}/{dd:+d}"
        else:
            delta = "--"
        wl = f"{s['won']}-{s['lost']}" if s["won"] is not None else "--"
        pl = (f"{s['planted']}/{s['n_rounds']}"
              if s["planted"] is not None and s["n_rounds"] else "--")
        lab = ",".join(f"{k.replace('minimap_', 'mm_')}:{v}"
                       for k, v in sorted(s["labels"].items())) or "--"
        rows.append((s["sid"], s["map"], f"{s['minutes']:.0f}",
                     str(s["n_rounds"] or "--"), wl, pl, kd, kn, delta,
                     "y" if s["geometry"] else "-", lab))
    w = [max(len(c), max((len(r[i]) for r in rows), default=0)) for i, c in enumerate(cols)]
    if markdown:
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join("---" for _ in cols) + "|")
        for r in rows:
            L.append("| " + " | ".join(r) + " |")
    else:
        L.append("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
        for r in rows:
            L.append("  ".join(r[i].ljust(w[i]) for i in range(len(cols))))
    L.append("")

    missing = [s["sid"] for s in ss if not s["hud"]]
    if missing:
        L.append(f"No HUD L1 (never `reticle hud`): {', '.join(missing)}")
    errs = [(s["sid"], s["error"]) for s in ss if s.get("error")]
    for sid, e in errs:
        L.append(f"ERROR building rounds for {sid}: {e}")
    if not markdown:
        L.append("")
        L.append("d = our K/D minus the scoreboard's. A positive delta is not")
        L.append("automatically an error -- see 'Scoreboard divergence is a finding'.")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--write", action="store_true",
                    help="write STATUS.md next to CLAUDE.md, in markdown")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args(argv)
    data = collect(Store(a.store))
    text = render(data, markdown=a.markdown or a.write)
    if a.write:
        p = Path(__file__).resolve().parent.parent / "STATUS.md"
        p.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {p} ({len(text) / 1024:.1f} KB)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
