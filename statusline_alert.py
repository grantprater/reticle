"""Statusline script and quota/context monitor for Antigravity.

Exposes live percentages for:
- 5-Hour Session Limit (Gemini 5h window)
- Weekly Limit (Gemini weekly quota)
- Active Context Size

Provides visual alerts when quota drops below warning thresholds.
Data is read directly and instantly from agy's stdin payload without
spawning external CLI subprocesses.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

CACHE_DIR = Path(r"C:\Users\grant\reticle\.cache")
CACHE_FILE = CACHE_DIR / "quota_cache.json"

ALERT_THRESHOLD_WARN = 0.20  # 20%
ALERT_THRESHOLD_CRIT = 0.08  # 8%


def read_cached_quota() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def update_cache(stdin_data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        to_store = {
            "timestamp": time.time(),
            "quota": stdin_data.get("quota"),
            "context_window": stdin_data.get("context_window"),
            "model": stdin_data.get("model"),
        }
        CACHE_FILE.write_text(json.dumps(to_store), encoding="utf-8")
    except Exception:
        pass


def parse_limits(stdin_data: dict, cached_data: dict) -> tuple[float, float, str, str]:
    """Returns (session_fraction, weekly_fraction, session_reset, weekly_reset)."""
    session_frac = 1.0
    weekly_frac = 1.0
    session_reset = ""
    weekly_reset = ""

    # 1. Prefer live quota directly from agy stdin payload
    quota = stdin_data.get("quota") if isinstance(stdin_data, dict) else None
    if isinstance(quota, dict) and quota:
        g5h = quota.get("gemini-5h", {})
        gw = quota.get("gemini-weekly", {})
        if "remaining_fraction" in g5h:
            session_frac = float(g5h.get("remaining_fraction", 1.0))
            session_reset = str(g5h.get("reset_time", ""))
        if "remaining_fraction" in gw:
            weekly_frac = float(gw.get("remaining_fraction", 1.0))
            weekly_reset = str(gw.get("reset_time", ""))
        return session_frac, weekly_frac, session_reset, weekly_reset

    # 2. Check cached data
    if isinstance(cached_data, dict):
        q = cached_data.get("quota")
        if isinstance(q, dict) and q:
            g5h = q.get("gemini-5h", {})
            gw = q.get("gemini-weekly", {})
            if "remaining_fraction" in g5h:
                session_frac = float(g5h.get("remaining_fraction", 1.0))
                session_reset = str(g5h.get("reset_time", ""))
            if "remaining_fraction" in gw:
                weekly_frac = float(gw.get("remaining_fraction", 1.0))
                weekly_reset = str(gw.get("reset_time", ""))
            return session_frac, weekly_frac, session_reset, weekly_reset

        # Check groups structure if cached from /usage
        groups = cached_data.get("groups", [])
        if isinstance(groups, list):
            for g in groups:
                if "gemini" in g.get("name", "").lower():
                    for b in g.get("buckets", []):
                        bid = b.get("id", "")
                        if "5h" in bid or b.get("window") == "5h":
                            session_frac = float(b.get("remaining_fraction", 1.0))
                            session_reset = str(b.get("reset_time", ""))
                        elif "weekly" in bid or b.get("window") == "weekly":
                            weekly_frac = float(b.get("remaining_fraction", 1.0))
                            weekly_reset = str(b.get("reset_time", ""))

    return session_frac, weekly_frac, session_reset, weekly_reset


def get_context_size(stdin_data: dict, cached_data: dict) -> str:
    # 1. Exact context usage from agy stdin payload
    cw = stdin_data.get("context_window") if isinstance(stdin_data, dict) else None
    if isinstance(cw, dict):
        total_tokens = cw.get("total_input_tokens")
        used_pct = cw.get("used_percentage")
        if total_tokens is not None:
            try:
                tok_int = int(total_tokens)
                if used_pct is not None:
                    pct = float(used_pct)
                    if tok_int >= 1000:
                        return f"{tok_int / 1000:.1f}k ({pct:.0f}%)"
                    return f"{tok_int} ({pct:.0f}%)"
                if tok_int >= 1000:
                    return f"{tok_int / 1000:.1f}k tok"
                return f"{tok_int} tok"
            except Exception:
                pass

    # 2. Check other token fields
    tokens = stdin_data.get("token_count") or stdin_data.get("tokens") or stdin_data.get("context_tokens")
    if tokens is not None:
        try:
            tok_int = int(tokens)
            if tok_int >= 1000:
                return f"{tok_int / 1000:.1f}k tok"
            return f"{tok_int} tok"
        except Exception:
            pass

    # 3. Cached context info
    cw_cached = cached_data.get("context_window") if isinstance(cached_data, dict) else None
    if isinstance(cw_cached, dict):
        total_tokens = cw_cached.get("total_input_tokens")
        used_pct = cw_cached.get("used_percentage")
        if total_tokens is not None:
            try:
                tok_int = int(total_tokens)
                if used_pct is not None:
                    return f"{tok_int / 1000:.1f}k ({float(used_pct):.0f}%)"
                return f"{tok_int / 1000:.1f}k tok"
            except Exception:
                pass

    # 4. Fallback: estimate from latest conversation transcript
    brain_dir = Path(r"C:\Users\grant\.gemini\antigravity-cli\brain")
    if brain_dir.exists():
        try:
            conv_dirs = [
                d for d in brain_dir.iterdir()
                if d.is_dir() and (d / ".system_generated" / "logs" / "transcript.jsonl").exists()
            ]
            if conv_dirs:
                latest = max(
                    conv_dirs,
                    key=lambda d: (d / ".system_generated" / "logs" / "transcript.jsonl").stat().st_mtime
                )
                log_file = latest / ".system_generated" / "logs" / "transcript.jsonl"
                est_tokens = int(log_file.stat().st_size / 4)
                if est_tokens > 1000:
                    return f"~{est_tokens / 1000:.1f}k tok"
                return f"~{est_tokens} tok"
        except Exception:
            pass

    return "active"


def format_statusline(stdin_data: dict) -> str:
    cached_data = read_cached_quota()

    if isinstance(stdin_data, dict) and ("quota" in stdin_data or "context_window" in stdin_data):
        update_cache(stdin_data)

    session_frac, weekly_frac, _, _ = parse_limits(stdin_data, cached_data)
    session_pct = int(round(session_frac * 100))
    weekly_pct = int(round(weekly_frac * 100))
    context_str = get_context_size(stdin_data, cached_data)

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
    if sys.stdin.isatty():
        return {}

    try:
        import msvcrt
        import ctypes
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        avail = wintypes.DWORD()
        kernel32 = ctypes.windll.kernel32
        success = kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        if success:
            if avail.value > 0:
                raw_bytes = sys.stdin.buffer.read(avail.value)
                return json.loads(raw_bytes.decode("utf-8", errors="replace"))
            return {}
        else:
            raw = sys.stdin.read()
            if raw.strip():
                return json.loads(raw)
    except Exception:
        pass
    return {}


def main():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

        stdin_data = read_stdin_json()
        output = format_statusline(stdin_data)
        print(output)
    except Exception:
        try:
            print("[Quota: active] [Context: active]")
        except Exception:
            pass


if __name__ == "__main__":
    main()
