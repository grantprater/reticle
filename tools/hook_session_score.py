"""Stop hook: upsert one objective record per session into the store.

    ~/reticle-store/notes/sessions.jsonl   (one line per session, keyed by session_id)

Why this exists
---------------
Nothing scored a Claude session. Corrections were recorded in memory prose
("said four times before it was recorded") and never counted, so no loop could
optimise against them. This hook reads the session transcript at every Stop
and rewrites the session's line, so the record is live and survives a session
that never ends cleanly.

What it records, and what it refuses to
---------------------------------------
Objective counts only: turns, tool calls, edits, files touched, test runs and
the last test verdict, commits, compactions, effort, model. `test_runs` is a
command-text match and counts a grep for "pytest" as a run; read `last_test`
as the verdict of the last command that looked like a test, not as proof one
ran. It does NOT count
corrections. A phrase regex was tried on 201 recorded prompts and matched two,
both false; a number that wrong is worse than a null. `corrections` stays null
here and is filled by a reader of the transcript (`transcript` names it), the
same way `tools/task_check.py --review-corrections` takes a counted value.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(os.environ.get("RETICLE_STORE", "~/reticle-store")).expanduser() / "notes" / "sessions.jsonl"
TEST_CMD = re.compile(r"\b(pytest|unittest|task_check\.py)\b")
COMMIT_CMD = re.compile(r"\bgit\s+commit\b")
FAIL_TEXT = re.compile(r"\b(\d+ failed|FAILED|Error|Traceback)\b")
PASS_TEXT = re.compile(r"\b(\d+ passed|OK\b|PASS\b)")


def _blocks(rec):
    m = rec.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), list):
        return [b for b in m["content"] if isinstance(b, dict)]
    return []


def score(transcript: Path, session_id: str) -> dict:
    row = dict(schema_version=1, session_id=session_id, transcript=str(transcript),
               started=None, last=None, turns=0, assistant_msgs=0, tool_calls=0,
               edits=0, files_touched=[], bash=0, test_runs=0, last_test=None,
               commits=0, compactions=0, effort={}, model=None, corrections=None)
    files = set()
    msg_ids = set()  # one assistant message streams as several records
    pending = {}  # tool_use id -> kind ("test") to read its result
    for line in transcript.open(encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ts = rec.get("timestamp")
        if ts:
            row["started"] = row["started"] or ts
            row["last"] = ts
        t = rec.get("type")
        if t == "system" and rec.get("subtype") == "compact_boundary":
            row["compactions"] += 1
        if t == "user" and not rec.get("isMeta"):
            c = rec.get("message", {}).get("content")
            if isinstance(c, str) or any(b.get("type") == "text" for b in _blocks(rec)):
                row["turns"] += 1
        if t == "assistant":
            mid = rec.get("message", {}).get("id") or rec.get("uuid")
            if mid not in msg_ids:
                msg_ids.add(mid)
                row["assistant_msgs"] += 1
                eff = rec.get("effort")
                if eff:
                    row["effort"][eff] = row["effort"].get(eff, 0) + 1
            model = rec.get("message", {}).get("model")
            if model:
                row["model"] = model
        for b in _blocks(rec):
            if b.get("type") == "tool_use":
                row["tool_calls"] += 1
                name, inp = b.get("name", ""), b.get("input") or {}
                if name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                    row["edits"] += 1
                    if inp.get("file_path"):
                        files.add(inp["file_path"])
                if name in ("Bash", "PowerShell"):
                    row["bash"] += 1
                    cmd = str(inp.get("command", ""))
                    if TEST_CMD.search(cmd):
                        row["test_runs"] += 1
                        pending[b.get("id")] = "test"
                    if COMMIT_CMD.search(cmd):
                        row["commits"] += 1
            if b.get("type") == "tool_result" and pending.pop(b.get("tool_use_id"), None):
                text = b.get("content")
                if isinstance(text, list):
                    text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                text = str(text or "")
                row["last_test"] = ("fail" if FAIL_TEXT.search(text)
                                    else "pass" if PASS_TEXT.search(text) else "unknown")
    row["files_touched"] = sorted(files)
    row["scored_at"] = datetime.now(timezone.utc).isoformat()
    return row


def upsert(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("session_id") != row["session_id"]:
                    kept.append(line)
            except ValueError:
                kept.append(line)
    kept.append(json.dumps(row, separators=(",", ":")))
    LOG.write_text("\n".join(kept) + "\n", encoding="utf-8")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    path = payload.get("transcript_path")
    sid = payload.get("session_id")
    if not path or not sid or not Path(path).is_file():
        return 0
    upsert(score(Path(path), sid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
