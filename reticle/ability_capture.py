"""CLI adapter for the targeted ability capture queue."""
from __future__ import annotations

import argparse
from pathlib import Path

from .adjudication.capture import build_queue, write_queue
from .store import DEFAULT_STORE


def run(root=DEFAULT_STORE, out=None):
    bundle = build_queue(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-capture"
    write_queue(bundle, target)
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
