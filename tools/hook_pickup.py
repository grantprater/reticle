"""SessionStart hook: hand the new session its pickup context.

Prints to stdout, which Claude Code adds to the session's context:

1. the current handoff (NOTES.md), the one part of status that stays prose;
2. the header of `reticle.status`, the generated numbers that must be quoted
   from here and never from prose;
3. doctor's summary line, with its ERROR lines when there are any.

It runs on startup, resume, clear and compact, so a compacted session gets the
handoff back.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def _run(*argv) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), *argv], cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    notes = ROOT / "NOTES.md"
    print("## Pickup: NOTES.md (current handoff)\n")
    print(notes.read_text(encoding="utf-8") if notes.exists() else "NOTES.md missing")

    status = _run("-m", "reticle.status")
    header = status.stdout.split("\nsession ", 1)[0].strip()
    print("\n## Pickup: reticle status (generated; quote these numbers, not NOTES.md's)\n")
    print(header or f"status printed nothing (exit {status.returncode})")

    run = _run("-m", "reticle", "doctor")
    lines = run.stdout.strip().splitlines()
    errors = [ln for ln in lines if ln.startswith("!!")]
    print("\n## Pickup: reticle doctor\n")
    print(lines[-1] if lines else f"doctor printed nothing (exit {run.returncode})")
    print("\n".join(errors))


if __name__ == "__main__":
    main()
