"""Stop hook: refuse to end a turn while the geometry guard or `reticle doctor`
reports an ERROR.

Reads the hook payload on stdin. When a check fails, prints a block decision
naming each ERROR line. A second stop attempt (`stop_hook_active`) passes, so
the hook asks once and never traps the session in a loop.

`tools/guard_geometry.py` runs every time (0.2 s). Doctor takes about 7 s and
Stop fires at the end of every turn, so doctor runs only when the working tree
has changed since its last clean run: `.claude/doctor.ok` (gitignored) holds
the fingerprint of the last tree that passed.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
STAMP = ROOT / ".claude" / "doctor.ok"


def _run(*argv) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), cwd=ROOT, capture_output=True, text=True)


def _fingerprint() -> str:
    """HEAD plus the porcelain status: changes when any tracked or new file does."""
    head = _run("git", "rev-parse", "HEAD").stdout.strip()
    status = _run("git", "status", "--porcelain").stdout
    return head + "\n" + status


def _block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    guard = _run(str(PY), str(ROOT / "tools" / "guard_geometry.py"))
    if guard.returncode != 0:
        return _block("GEOMETRY GUARD FAILED: the art-derived map path is broken.\n"
                      + (guard.stdout + guard.stderr)[-2000:])

    tree = _fingerprint()
    if STAMP.is_file() and STAMP.read_text(encoding="utf-8") == tree:
        return 0
    run = _run(str(PY), "-m", "reticle", "doctor")
    if run.returncode == 0:
        STAMP.parent.mkdir(exist_ok=True)
        STAMP.write_text(tree, encoding="utf-8")
        return 0
    errors = [ln.strip() for ln in run.stdout.splitlines() if ln.startswith("!!")]
    return _block("reticle doctor reports ERRORs; fix them or say why they stand:\n"
                  + "\n".join(errors or [run.stdout[-2000:] + run.stderr[-1000:]]))


if __name__ == "__main__":
    sys.exit(main())
