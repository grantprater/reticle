"""Append `scan --check` timing rows to the store's notes, append only.

`scan --check` writes each path's usage row and `scan_usage` pass row into
its own temporary store under the check directory, where QUOTED does not
look. This copies them into `<store>/notes/usage.jsonl` and
`<store>/notes/metrics.jsonl` byte for byte, so a document can cite them.

    python tools/pubsub_notes_append.py CHECK_DIR [CHECK_DIR ...] [--store PATH] [--dry-run]

Each CHECK_DIR must hold `a/` and `b/`, each with exactly one usage row and
exactly one pass row naming that usage row's run_id. It refuses the whole
batch, appending nothing, when any run_id is already in the store's usage
or metrics notes or appears twice in the batch. It prints every row it
appends. Timings are notes, not derived data: nothing else is written.
"""
import argparse
import json
from pathlib import Path


def lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [l.rstrip("\r\n") for l in path.open(encoding="utf-8") if l.strip()]


def metric_run_id(row: dict):
    return row.get("usage_run_id") or (row.get("context") or {}).get("usage_run_id")


def collect(check_dir: Path) -> list[tuple[str, str, str]]:
    """(run_id, usage line, metrics line) for paths a and b of one check."""
    out = []
    for side in ("a", "b"):
        notes = check_dir / side / "notes"
        us, ms = lines(notes / "usage.jsonl"), lines(notes / "metrics.jsonl")
        passes = [m for m in ms if json.loads(m).get("tool") == "scan_usage"]
        if len(us) != 1 or len(passes) != 1:
            raise SystemExit(f"{notes}: want one usage row and one pass row, "
                             f"found {len(us)} and {len(passes)}")
        rid = json.loads(us[0])["run_id"]
        if metric_run_id(json.loads(passes[0])) != rid:
            raise SystemExit(f"{notes}: the pass row does not name usage run {rid}")
        out.append((rid, us[0], passes[0]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("check_dirs", nargs="+", type=Path)
    ap.add_argument("--store", type=Path, default=Path.home() / "reticle-store")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    notes = args.store / "notes"
    usage_path, metrics_path = notes / "usage.jsonl", notes / "metrics.jsonl"
    present = {json.loads(l).get("run_id") for l in lines(usage_path)}
    present |= {metric_run_id(json.loads(l)) for l in lines(metrics_path)}
    present.discard(None)

    batch = [row for d in args.check_dirs for row in collect(d)]
    ids = [rid for rid, _, _ in batch]
    dup = sorted({r for r in ids if ids.count(r) > 1} | (set(ids) & present))
    if dup:
        raise SystemExit(f"refused: run_id already present or repeated: {', '.join(dup)}")

    for rid, u, m in batch:
        print(f"usage   {usage_path}  {u}")
        print(f"metrics {metrics_path}  {m}")
    if args.dry_run:
        print(f"dry run: {len(batch)} usage and {len(batch)} metrics rows not appended")
        return 0
    # Text mode, as `usage.write` and `metrics.record` write: one line per row.
    for path, rows in ((usage_path, [u for _, u, _ in batch]),
                       (metrics_path, [m for _, _, m in batch])):
        lead = path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n")
        with path.open("a", encoding="utf-8") as out:
            out.write(("\n" if lead else "") + "".join(r + "\n" for r in rows))
    print(f"appended {len(batch)} usage and {len(batch)} metrics rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
