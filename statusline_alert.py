"""Statusline script and quota/context monitor for Antigravity.

Exposes live percentages for:
- 5-Hour Session Limit (Gemini 5h window)
- Weekly Limit (Gemini weekly quota)
- Active Context Size

Provides visual alerts when quota drops below warning thresholds.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CACHE_DIR = Path(r"C:\Users\grant\reticle\.cache")
CACHE_FILE = CACHE_DIR / "quota_cache.json"
CACHE_TTL_SEC = 30.0

ALERT_THRESHOLD_WARN = 0.20  # 20%
ALERT_THRESHOLD_CRIT = 0.08  # 8%


AGY_BIN = r"C:\Users\grant\AppData\Local\agy\bin\agy.exe"


def get_quota_data() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()

    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if now - cached.get("timestamp", 0) < CACHE_TTL_SEC:
                return cached.get("data", {})
        except Exception:
            pass

    try:
        res = subprocess.run(
            [AGY_BIN, "--output-format", "json", "-p", "/usage"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw = json.loads(res.stdout)
            cmd_data = raw.get("command", {}).get("data", {})
            CACHE_FILE.write_text(
                json.dumps({"timestamp": now, "data": cmd_data}),
                encoding="utf-8",
            )
            return cmd_data
    except Exception:
        pass

    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8")).get("data", {})
        except Exception:
            pass

    return {}


def parse_limits(quota_data: dict) -> tuple[float, float, str, str]:
    """Returns (session_fraction, weekly_fraction, session_reset, weekly_reset)."""
    session_frac = 1.0
    weekly_frac = 1.0
    session_reset = ""
    weekly_reset = ""

    groups = quota_data.get("groups", [])
    for g in groups:
        if "gemini" in g.get("name", "").lower():
            for b in g.get("buckets", []):
                bid = b.get("id", "")
                if "5h" in bid or b.get("window") == "5h":
                    session_frac = float(b.get("remaining_fraction", 1.0))
                    session_reset = b.get("reset_time", "")
                elif "weekly" in bid or b.get("window") == "weekly":
                    weekly_frac = float(b.get("remaining_fraction", 1.0))
                    weekly_reset = b.get("reset_time", "")

    return session_frac, weekly_frac, session_reset, weekly_reset


def get_context_size(stdin_data: dict) -> str:
    # 1. Check stdin payload if available
    tokens = stdin_data.get("token_count") or stdin_data.get("tokens") or stdin_data.get("context_tokens")
    if tokens is not None:
        try:
            tok_int = int(tokens)
            if tok_int > 1000:
                return f"{tok_int / 1000:.1f}k tokens"
            return f"{tok_int} tokens"
        except Exception:
            pass

    # 2. Estimate from active conversation logs if available
    brain_dir = Path(r"C:\Users\grant\.gemini\antigravity-cli\brain")
    if brain_dir.exists():
        conv_dirs = [d for d in brain_dir.iterdir() if d.is_dir() and (d / ".system_generated" / "logs" / "transcript.jsonl").exists()]
        if conv_dirs:
            latest = max(conv_dirs, key=lambda d: (d / ".system_generated" / "logs" / "transcript.jsonl").stat().st_mtime)
            log_file = latest / ".system_generated" / "logs" / "transcript.jsonl"
            size_kb = log_file.stat().st_size / 1024
            # Rule of thumb: ~4 chars per token, roughly 0.25 tokens per byte
            est_tokens = int(log_file.stat().st_size / 4)
            if est_tokens > 1000:
                return f"~{est_tokens / 1000:.1f}k tok"
            return f"~{est_tokens} tok"

    return "active"


def format_statusline(stdin_data: dict) -> str:
    quota_data = get_quota_data()
    session_frac, weekly_frac, _, _ = parse_limits(quota_data)
    session_pct = int(round(session_frac * 100))
    weekly_pct = int(round(weekly_frac * 100))
    context_str = get_context_size(stdin_data)

    alert_prefix = ""
    if session_frac <= ALERT_THRESHOLD_CRIT or weekly_frac <= ALERT_THRESHOLD_CRIT:
        alert_prefix = "🚨 [QUOTA CRITICAL] "
    elif session_frac <= ALERT_THRESHOLD_WARN or weekly_frac <= ALERT_THRESHOLD_WARN:
        alert_prefix = "⚠️ [QUOTA WARN] "

    status = (
        f"{alert_prefix}[Quota: Session (5h): {session_pct}% | Weekly: {weekly_pct}%] "
        f"[Context: {context_str}]"
    )
    return status


def read_stdin_json() -> dict:
    try:
        import msvcrt
        import ctypes
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        avail = wintypes.DWORD()
        kernel32 = ctypes.windll.kernel32
        success = kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        if success and avail.value > 0:
            raw = sys.stdin.read(avail.value)
            try:
                return json.loads(raw)
            except Exception:
                return {}
    except Exception:
        pass
    return {}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    stdin_data = read_stdin_json()
    output = format_statusline(stdin_data)
    print(output)


if __name__ == "__main__":
    main()
