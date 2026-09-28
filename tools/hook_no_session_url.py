"""PreToolUse hook: refuse a Write, Edit or Bash call that carries a Claude
session URL, so none reaches a repository file or a commit message.

Exit 2 blocks the call and hands stderr back to Claude.
"""
import json
import re
import sys

SESSION_URL = re.compile(r"claude\.ai/(?:code/)?(?:sessions?|chats?)[_/][\w-]+", re.I)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    text = json.dumps(payload.get("tool_input", {}))
    hit = SESSION_URL.search(text)
    if hit:
        print(f"Blocked: '{hit.group(0)}' is a Claude session URL. Session URLs "
              "never go in repository files or commit messages (AGENTS.md).",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
