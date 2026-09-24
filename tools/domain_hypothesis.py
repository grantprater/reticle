"""Import and review one stored-data domain hypothesis; never edit domain facts."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.cli import main as cli_main


def main() -> int:
    return cli_main(["domain-hypothesis", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
