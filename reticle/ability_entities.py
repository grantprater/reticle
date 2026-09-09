"""CLI adapter for ability entity hypotheses."""
from __future__ import annotations

import argparse
from pathlib import Path

from .adjudication.ability import build_entities, write_entities
from .store import DEFAULT_STORE


def run(root=DEFAULT_STORE, out=None):
    bundle = build_entities(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-entities"
    write_entities(bundle, target)
    return bundle, target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    bundle, target = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    print(f"{summary['components']} components; {summary['component_parent_edges']} parent edges; "
          f"{summary['entity_hypotheses']} entity hypotheses")
    print(f"{summary['supported_parent_edges']} supported parent edges; "
          f"{summary['review_windows']} unresolved review windows")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
