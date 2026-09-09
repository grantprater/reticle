"""CLI adapter for entity phases and their transition causes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adjudication.ability import _components, _labels
from .adjudication.phases import (ABILITY_PHASE_VERSION, TRANSITION_CAUSES,
                                  entity_phases, summarise)
from .store import DEFAULT_STORE


def ally_deaths(root, session: str) -> list[float]:
    """Distinct ally killfeed entries, through the shipped tracker."""
    import duckdb

    from .checks import track_entries

    pattern = str(Path(root) / "l1" / "hud" / "**" / "*.parquet").replace("\\", "/")
    con = duckdb.connect()
    try:
        rows = con.execute(
            "select t_ms, kf_ally_mask, kf_entry_wx from read_parquet(?) "
            "where session = ? order by t_ms", [pattern, session]).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    if not rows:
        return []
    return sorted(a["t_first"] for a in track_entries(
        [r[0] for r in rows], [r[1] or 0 for r in rows], [r[2] for r in rows])
        if a["counted"])


def run(root=DEFAULT_STORE, out=None):
    root = Path(root)
    components = _components(root, _labels(root))
    by_session: dict[str, list] = {}
    for component in components:
        if component["label_state"] == "named":
            by_session.setdefault(component["session_id"], []).append(component)
    rows, deaths_seen = [], {}
    for session, group in sorted(by_session.items()):
        deaths = ally_deaths(root, session)
        deaths_seen[session] = len(deaths)
        rows += entity_phases(root, session, group, deaths)
    bundle = {
        "manifest": {
            "schema_version": 2, "producer_version": ABILITY_PHASE_VERSION,
            "store_root": str(root), "summary": summarise(rows),
            "ally_death_events": deaths_seen,
            "transition_causes": list(TRANSITION_CAUSES),
            "limits": [
                "Bright/dim are measured appearance candidates, not active/inactive states.",
                "Appearance support does not establish existence through a coverage gap.",
                "A cause is never asserted. An unexplained transition is a flag.",
                "owner_death rests on an ALLY killfeed entry, not on the device's own "
                "owner: survivors pack in the roster bar, so a slot is not an identity.",
                "The radius cause is listed as unavailable rather than omitted, because "
                "no owner track exists for a non-local player.",
            ],
        },
        "phases": rows,
    }
    target = Path(out) if out else root / "analysis" / "ability-phases"
    target.mkdir(parents=True, exist_ok=True)
    (target / "phases.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    (target / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return bundle, target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    _, target = run(args.store, args.out)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
