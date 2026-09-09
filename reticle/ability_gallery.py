"""CLI adapter for ability appearance galleries and held-out evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

from .adjudication.gallery import build_gallery_bundle, write_gallery
from .store import DEFAULT_STORE


def run(root=DEFAULT_STORE, out=None):
    bundle = build_gallery_bundle(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-gallery"
    write_gallery(bundle, target)
    return bundle, target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    bundle, target = run(args.store, args.out)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
