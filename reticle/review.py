"""Review selection is a pure projection, not an event or model definition.

Keep one chronological event per resolved round and one ordinary control per
round with eligible states. The control is the lower median unique timestamp:
neither outcomes, model estimates nor proximity to events influence selection.
It is conditional on the coaching phase/roster gate, not representative of all
play and not evidence of no contact. No pixels are decoded here.
"""
from __future__ import annotations

import hashlib

REVIEW_VERSION = "review-0.1.0"
WINDOW_BEFORE_MS = 8000
WINDOW_AFTER_MS = 6000


def _round(contexts, sid, number):
    for r in contexts.get(sid, {}).get("rounds", []):
        if r.get("round_no") == number:
            return r
    return None


def _row(kind, sid, round_no, t, start, end, source, reason, event_id=None, overlap=()):
    if not start < end or not start <= t < end:
        return None
    key = f"{REVIEW_VERSION}:{kind}:{sid}:{round_no}:{t:.3f}"
    out = dict(review_id=hashlib.sha256(key.encode()).hexdigest()[:20], review_version=REVIEW_VERSION,
               review_kind=kind, session_id=sid, round_no=round_no, t_ms=float(t),
               source_path=source, clip_start_ms=float(start), clip_end_ms=float(end),
               selection_reason=reason, observed_kind=None)
    if event_id is not None:
        out["event_id"] = event_id
    if kind == "ordinary_state_control":
        out["overlapping_event_ids"] = sorted(overlap)
    return out


def select_review_windows(events, states, contexts):
    """Select one event and one ordinary state control per resolved round."""
    by_round = {}
    for e in sorted(events, key=lambda x: (x.get("session_id", ""), x.get("round_no") is None,
                                           x.get("round_no") or 0, x.get("t_ms", 0), x.get("event_id", ""))):
        if e.get("round_no") is not None:
            by_round.setdefault((e["session_id"], e["round_no"]), []).append(e)
    result = []
    for key, es in sorted(by_round.items()):
        e = es[0]
        sid, rn, r = key[0], key[1], _round(contexts, *key)
        if not r:
            continue
        ctx = contexts.get(sid, {})
        lo, hi = float(r["t_start_ms"]), float(r["t_end_ms"])
        if ctx.get("duration_ms") is not None:
            hi = min(hi, float(ctx["duration_ms"]))
        start = max(0.0, lo, float(e.get("clip_start_ms", e["t_ms"] - WINDOW_BEFORE_MS)))
        end = min(hi, float(e.get("clip_end_ms", e["t_ms"] + WINDOW_AFTER_MS)))
        row = _row("event", sid, rn, e["t_ms"], start, end,
                           e.get("source_path") or ctx.get("source_path"),
                           "one event per round", e.get("event_id"))
        if row:
            row["observed_kind"] = e.get("kind")
            result.append(row)
    state_groups = {}
    for s in states:
        if s.get("round_no") is not None:
            state_groups.setdefault((s["session_id"], s["round_no"]), []).append(s)
    for key, ss in sorted(state_groups.items()):
        r = _round(contexts, *key)
        if not r:
            continue
        times = sorted({float(s["t_ms"]) for s in ss})
        median = times[(len(times) - 1) // 2]
        s = min(ss, key=lambda x: (abs(float(x["t_ms"]) - median), float(x["t_ms"])))
        lo, hi = float(r["t_start_ms"]), float(r["t_end_ms"])
        ctx = contexts.get(key[0], {})
        if ctx.get("duration_ms") is not None:
            hi = min(hi, float(ctx["duration_ms"]))
        cstart = max(0.0, lo, float(s["t_ms"]) - WINDOW_BEFORE_MS)
        cend = min(hi, float(s["t_ms"]) + WINDOW_AFTER_MS)
        overlaps = [e.get("event_id") for e in by_round.get(key, [])
                    if cstart <= float(e["t_ms"]) < cend]
        row = _row("ordinary_state_control", key[0], key[1], s["t_ms"],
                           cstart, cend,
                           ctx.get("source_path"), "temporal median eligible state",
                           overlap=overlaps)
        if row:
            result.append(row)
    return sorted(result, key=lambda x: (x["session_id"], x["t_ms"],
                                          x["review_kind"], x["review_id"]))


def render_review(rows, status):
    lines = ["# Reticle review queue", "", f"Probability evaluation: {status}.", "",
             "Controls are eligible states, not verified no-contact examples; they may overlap events.",
             "Selection is conditional on roster/clock coverage, not representative of all play.",
             "Review windows are clamped to resolved round and source bounds; timing is not refined.",
             "Open the source and seek to the listed time; no clips have been exported.", "",
             "| ID | Type | Session | Round | Time (s) | Window (s) | Evidence IDs | Selection | Source |",
             "|---|---|---|---:|---:|---|---|---|---|"]
    for r in rows:
        src = (r.get("source_path") or "unavailable").replace("|", "\\|")
        if r.get("source_path"):
            src = f"[Open video](<{src.replace(chr(92), '/')}>)"
        kind = r.get('observed_kind') or r['review_kind']
        evidence = r.get('event_id') or ', '.join(r.get('overlapping_event_ids', [])) or 'none observed'
        lines.append(f"| {r['review_id']} | {kind} | {r['session_id']} | {r['round_no']} | "
                     f"{r['t_ms']/1000:.1f} | {r['clip_start_ms']/1000:.1f}-{r['clip_end_ms']/1000:.1f} | "
                     f"{evidence} | {r['selection_reason']} | {src} |")
    return "\n".join(lines) + "\n"
