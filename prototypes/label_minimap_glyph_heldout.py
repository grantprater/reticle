r"""A held-out labelling pass for minimap ability icons in the solo demos.

    .\.venv\Scripts\python.exe prototypes\label_minimap_glyph_heldout.py queue     [--rebuild]  (build once, from the crop cache; fixed after)
    .\.venv\Scripts\python.exe prototypes\label_minimap_glyph_heldout.py list      (counts and the time estimate)
    .\.venv\Scripts\python.exe prototypes\label_minimap_glyph_heldout.py label     [--by player]
    .\.venv\Scripts\python.exe prototypes\label_minimap_glyph_heldout.py label --headless SCRIPT.json [--labels DIR]
    .\.venv\Scripts\python.exe prototypes\label_minimap_glyph_heldout.py --pass sonic queue|list|label [--queue FILE]

`--pass sonic` (since 2026-10-04) runs a second, separate held-out pass for
`prototypes/sonic_square.py` over MATCH sessions, with its own queue, labels
and instructions; see "The Sonic Sensor pass" below. Without it the tool is
the glyph pass described next, unchanged.

Why. `minimap_glyph_eval.py`'s held-out score is contaminated: its follow
parameters were chosen after viewing held-out montages (store
`notes/predictions.jsonl`, minimap-glyph-follow-20261004), and its labels
cover six abilities. This pass gives a fresh held-out set across every demo
agent whose kit draws a minimap icon.

The split, fixed before any item is labelled. Every label this tool writes is
HELD-OUT for `prototypes/minimap_glyph_eval.py` and anything that succeeds it:
nobody tunes a parameter, template, threshold or rule on these labels or on
the queue's crops, and a method is scored on them once per version. Three
subsets are reported apart and never pooled into the headline: items from the
evaluation's dev sessions (`dev_session`, its `DEV` set at queue time),
items within [-0.5 s, +3.5 s] of a positioned label the earlier tuning saw
(`near_tuned_label`; labels/ability, ability_paint, tray_object), and the
audit of the exclusion prior (`audit_excluded`, below). The split
is also logged in the store's `notes/predictions.jsonl`
(minimap-label-pass-20261004).

Sample, by opportunity only; no detector output chooses an item.
* Opportunities are the demo truth: the player-confirmed census casts in
  `labels/demo_cast_class` (tray-gated drops, `demo_cast_census.py`).
* An ability is in scope unless the player's earlier answer
  (`labels/minimap_glyph_questions/answers.jsonl`, the `drawing` key, else
  the `ally` key, the last sure row winning) says it draws `nothing` or only a
  `shape`, or words to that effect (`OTHER_NO_ICON`); an unsure or missing
  answer keeps it. Every agent and ability with a minimap icon in the demos
  is covered.
* Those answers name the ally and enemy views only; the demos are the self
  view. That self draws as ally draws
  [domain:minimap/ability-drawing-colour-by-side] is a prior, so it is
  audited: one frame AUDIT_S (+1 s) after each excluded ability's earliest
  cast (smallest t_cast_ms, then session id), the no-icon agents included,
  flagged `audit_excluded` and scored apart from the held-out headline. The
  headline reads items of `kind` after_cast or control; an audit frame that
  lands on such a frame serves both, flagged and keeping its kind.
* Per kept cast, the frames at +1.0 s and +3.0 s after the refined cast
  time (`OFFSETS_S`, fixed in advance); per session, one control frame 1 s
  before its first cast (any slot), a frame where no new ability has been
  cast. The nearest held crop-cache sample stands for each; two casts asking
  the same sample share one item and both stay in its `opportunity`.

What the player marks. Each item is one whole minimap frame. Click the centre
of EVERY ability icon (glyph) on the minimap, whoever cast it, then name it
with a digit. Shapes (areas, lines, walls) are not marked; an icon_and_shape
ability is marked at its icon. Teammate and self portraits, pings and the
spike are not ability icons.
    left click     place a mark (a ring), then name it:
    1-4            the session agent's C, Q, E, X (the kit row shows which)
    5              a smoke whose caster you cannot tell (this agent's own
                   smoke takes its kit digit); a smoke's drawing names no
                   agent [domain:abilities/smoke-attribution]
    6              an ability of another agent than this session's
    7              other (type it)
    U              with an unnamed mark: an icon here, ability unsure (kept
                   out of the naming score, kept in detection); with no
                   marks: the whole item unsure, kept out of scoring
    Z X C V        the last mark's view: self, teammate, enemy, spectator
                   (default: the session's view from its manifest tag;
                   the demos tagged `spectator` default to spectator)
    right click    undo the last mark
    SPACE / D      save and advance (every mark named)
    N              no ability icon in this frame (a claim, never a default)
    A              back one      Q / ESC   save and quit
Nothing is seeded: no detector's answer is shown or preselected. The frame
1 s before the item's cast sits beside it for comparison only.

Files. The queue (`queue`) writes `<store>/analysis/minimap-label-pass-20261004/`:
`queue.json` and lossless PNG crops of the minimap ROI from the crop cache
(`roi_cache`, no decode). Answers append to
`<store>/labels/minimap_glyph_heldout/<session>.jsonl`, flushed per row; the
last row for a key wins, and a rerun resumes at the first unanswered item.
Mark coordinates are minimap ROI pixels of the stored crop (`coords`, `roi`).

The Sonic Sensor pass (`--pass sonic`). A fresh held-out set for
`sonic_square.py` from sonic-square-0.2.0 on: the earlier set held one
sensor, in a demo now used as dev. Fixed before any item is labelled, and
logged in the store's `notes/predictions.jsonl` (sonic-square-20261004, kind
split):
* Opportunities are match sessions (capture longer than SONIC_MIN_MATCH_MIN)
  whose stored lineup names Deadlock on either side, as `lineup.load_lineup`
  and `identity.side_candidates` name it (the agent-identity owner), minus
  `sonic_square.py`'s dev sessions.
* Queue 0.2.0 (`queue-0.2.0.json`, the default): in each such session's
  stored rounds (`Store.read_rounds`), every SONIC_ROUND_STRIDE-th round from
  round SONIC_ROUND_FIRST (every 5th from the 2nd), and in each, the frames
  SONIC_OFFSETS_S after the start of the round's CACHED span while at or
  before its last held sample. The cached span is the longest run of held
  minimap crop-cache samples inside the round whose steps are all at most
  SONIC_MAX_GAP_MS (`cached_span`). The match caches hold no minimap sample
  for the first 11-42 s of a round (most near 27 s; steps are 66-83 ms
  elsewhere), so offsets from the round's start sampled by where the cache
  begins, not by the round: queue 0.1.0 (`queue.json`, every 3rd round, +25 s
  and +60 s from the round start) kept 20 frames at +60 s and 3 at +25 s, and
  stays on disk unlabelled (`--queue queue.json`). The nearest held sample
  stands for each frame. No detector output, and no look at the frames,
  chose an item.
* The player clicks the centre of EVERY Sonic Sensor icon (Deadlock's Q),
  whoever placed it, lit or dim, and names it 2 (Q); U if unsure. Other
  Deadlock icons may be marked with their digit. N = no Sonic Sensor icon on
  the minimap (a claim). The default view is the side the lineup puts
  Deadlock on (teammate or enemy; self where the lineup names the player
  Deadlock). The comparison frame is SONIC_BEFORE_S before the item,
  clamped to the cached span's start.
Answers append to `<store>/labels/sonic_square_heldout/<session>.jsonl`;
the queue and crops live in `<store>/analysis/sonic-square-label-pass-20261004/`.
Nobody tunes `sonic_square.py` on them; each version is scored once.

Wire: no. A labelling tool; `minimap_glyph_eval.py` and `sonic_square.py`
score against its labels, and nothing in reticle/ runs it.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)

VERSION = "minimap-glyph-heldout-labels-0.1.0"
QUEUE_VERSION = "minimap-glyph-heldout-queue-0.2.0"
STORE = Path("C:/Users/grant/reticle-store")
QDIR = STORE / "analysis" / "minimap-label-pass-20261004"
LABEL_DIR = STORE / "labels" / "minimap_glyph_heldout"
ANSWERS = STORE / "labels" / "minimap_glyph_questions" / "answers.jsonl"
CAT = STORE / "reference" / "abilities.json"
OFFSETS_S = (1.0, 3.0)        # frames after each kept cast, fixed before labelling
CONTROL_S = -1.0              # one control frame this long before a session's first cast
AUDIT_S = 1.0                 # the audit frame after an excluded ability's earliest cast
BEFORE_S = -1.0               # the comparison frame, relative to the item's cast
TUNED_WINDOW_MS = (-500.0, 3500.0)   # an item this near a tuned label is flagged near_tuned_label
NO_ICON = {"nothing", "shape"}       # the player's drawing answers that rule an icon out
#: `other` answers whose words rule an icon out ("nothing, then the green/blue tint ... where gekko can pick it up").
OTHER_NO_ICON = {"visibility:Gekko:C:ally", "visibility:Gekko:E:ally"}
SECONDS_PER_ITEM = 10.0      # estimate: the click tools' mean ~6 s per item (tray_object, demo_cast_class), plus naming
BUDGET_MIN = 45.0
SLOTS = "CQEX"

# --- the Sonic Sensor pass, fixed before any item is labelled
SONIC_QDIR = STORE / "analysis" / "sonic-square-label-pass-20261004"
SONIC_LABEL_DIR = STORE / "labels" / "sonic_square_heldout"
SONIC_QUEUE_VERSION = "sonic-square-heldout-queue-0.2.0"
#: Queue 0.1.0 is `queue.json` (unlabelled, offsets from the round start); 0.2.0 is written beside it.
SONIC_QUEUE_FILE = "queue-0.2.0.json"
SONIC_AGENT = "Deadlock"
SONIC_MIN_MATCH_MIN = 15.0
SONIC_ROUND_FIRST, SONIC_ROUND_STRIDE = 2, 5
#: Offsets from the start of the round's cached span (`cached_span`), not from the round start.
SONIC_OFFSETS_S = (5.0, 35.0)
SONIC_BEFORE_S = -5.0
#: A step between held samples longer than this ends a cached span; an asked frame whose
#: nearest held sample is further than this is dropped, with the reason.
SONIC_MAX_GAP_MS = 1000.0
SONIC_TEXT = (
    "Click the centre of EVERY Sonic Sensor icon (Deadlock's Q) on the minimap, whoever placed it, lit or dim, "
    "and name it 2. Other Deadlock icons may take their digit (1-4); 6 another agent's ability; 7 other (type).\n"
    "U = last mark unsure (or the whole item, with no marks); Z/X/C/V = last mark's view self/teammate/"
    "enemy/spectator; right-click undo; SPACE/D save; N = no Sonic Sensor icon; A back; Q/ESC quit.")
VIEWS = {"z": "self", "x": "teammate", "c": "enemy", "v": "spectator"}
NAMES = {"5": "smoke", "6": "other_agent", "7": "other"}


# ------------------------------------------------------------------ inputs (pure where testable)

def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def player_drawing(rows: list[dict]) -> dict:
    """(agent, slot) -> (answer, other, key) from the player's sure visibility answers: the `drawing` key, else the
    `ally` key (the view facts make the teammate's view the drawing; `ask_minimap_glyphs.answered`), last row wins."""
    last = {}
    for r in rows:
        last[r["key"]] = r
    out = {}
    for k, r in last.items():
        parts = k.split(":")
        if parts[0] != "visibility" or len(parts) != 4 or r.get("unsure"):
            continue
        _, agent, slot, view = parts
        if view == "drawing" or (view == "ally" and (agent, slot) not in out):
            out[(agent, slot)] = (r.get("answer"), r.get("other"), k)
    return out


def icon_scope(drawing: dict, agent: str, slot: str) -> tuple[bool, str]:
    a = drawing.get((agent, slot))
    if a is None:
        return True, "no sure answer"
    if a[0] in NO_ICON or a[2] in OTHER_NO_ICON:
        return False, f"player: {a[0]}{' - ' + a[1] if a[1] else ''} ({a[2]})"
    return True, f"player: {a[0]}{' - ' + a[1] if a[1] else ''} ({a[2]})"


def demo_casts(store=STORE) -> list[dict]:
    """The player-confirmed census casts, last row per key."""
    last = {}
    for f in sorted(glob.glob(str(Path(store) / "labels" / "demo_cast_class" / "*.jsonl"))):
        for r in read_jsonl(f):
            last[r["key"]] = r
    return sorted(last.values(), key=lambda r: (r["session_id"], float(r["t_cast_ms"]), r["slot"]))


def tuned_label_times(store=STORE) -> dict:
    """{session: [t_ms]} of every positioned label the earlier glyph tuning read (minimap_glyph_eval.load_items)."""
    out = defaultdict(list)
    lab = Path(store) / "labels"
    for f in glob.glob(str(lab / "ability" / "*.jsonl")) + glob.glob(str(lab / "ability_paint" / "*.jsonl")):
        if "bak" in f:
            continue
        for r in read_jsonl(f):
            out[r["session_id"]].append(float(r["t_ms"]))
    for f in glob.glob(str(lab / "tray_object" / "*.jsonl")):
        for r in read_jsonl(f):
            out[r["session_id"]] += [float(m["t_ms"]) for m in r.get("marks", [])]
    return dict(out)


def nearest(holds: np.ndarray, t: float) -> float:
    return float(holds[int(np.argmin(np.abs(holds - t)))])


def plan_items(casts: list[dict], drawing: dict, holds: dict, views: dict, dev: set, tuned: dict) -> tuple:
    """(items, excluded casts). Items are keyed by (session, held sample); order: session, then time."""
    items, excluded = {}, []
    first = {}
    for c in casts:
        first.setdefault(c["session_id"], c)
    kept_sessions = set()
    for c in casts:
        sid = c["session_id"]
        ok, why = icon_scope(drawing, c["agent"], c["slot"])
        if not ok:
            excluded.append({"key": c["key"], "agent": c["agent"], "slot": c["slot"], "ability": c["ability"],
                             "why": why})
            continue
        if sid not in holds:
            excluded.append({"key": c["key"], "agent": c["agent"], "slot": c["slot"], "ability": c["ability"],
                             "why": "no minimap crop cache"})
            continue
        kept_sessions.add(sid)
        tc = float(c["t_cast_ms"])
        for off in OFFSETS_S:
            _add(items, sid, nearest(holds[sid], tc + off * 1000), tc + off * 1000, "after_cast", c, off)
    for sid in sorted(kept_sessions):
        c = first[sid]
        t = float(c["t_cast_ms"]) + CONTROL_S * 1000
        if t >= 0:
            _add(items, sid, nearest(holds[sid], t), t, "control", c, CONTROL_S)
    # The audit of the exclusion prior: one frame per excluded ability, from its earliest cast
    # (smallest t_cast_ms, then session id), at AUDIT_S.
    audit = {}
    for c in sorted(casts, key=lambda c: (float(c["t_cast_ms"]), c["session_id"])):
        if c["session_id"] in holds and not icon_scope(drawing, c["agent"], c["slot"])[0]:
            audit.setdefault((c["agent"], c["slot"]), c)
    for c in audit.values():
        sid, t = c["session_id"], float(c["t_cast_ms"]) + AUDIT_S * 1000
        _add(items, sid, nearest(holds[sid], t), t, "audit_excluded", c, AUDIT_S)
    out = []
    for (sid, th), it in sorted(items.items()):
        lo, hi = TUNED_WINDOW_MS
        roles = {o["role"] for o in it["opportunity"]}
        it.update({"view_default": views.get(sid, "self"), "dev_session": sid in dev,
                   "near_tuned_label": any(lo <= th - t <= hi for t in tuned.get(sid, [])),
                   "audit_excluded": "audit_excluded" in roles})
        it["kind"] = ("after_cast" if "after_cast" in roles else
                      "audit_excluded" if "audit_excluded" in roles else "control")
        out.append(it)
    return out, excluded


def _add(items: dict, sid: str, th: float, t_asked: float, role: str, cast: dict, off: float) -> None:
    it = items.setdefault((sid, th), {"key": f"{sid}:{int(round(th))}", "session_id": sid, "t_ms": th,
                                      "agent": cast["agent"], "opportunity": [],
                                      "t_before_ms": float(cast["t_cast_ms"]) + BEFORE_S * 1000})
    it["opportunity"].append({"cast": cast["key"], "slot": cast["slot"], "ability": cast["ability"], "role": role,
                              "offset_s": off, "t_asked_ms": t_asked})


def cached_span(holds: np.ndarray, t0: float, t1: float | None) -> tuple[float, float] | None:
    """(first, last) held time of the longest run of held samples inside [t0, t1] whose steps are all
    at most SONIC_MAX_GAP_MS; None if the round holds no sample. The earliest run wins a tie."""
    h = np.sort(np.asarray(holds, dtype=float))
    h = h[(h >= t0) & ((h <= t1) if t1 is not None else True)]
    if not len(h):
        return None
    cut = np.flatnonzero(np.diff(h) > SONIC_MAX_GAP_MS) + 1
    starts, ends = np.r_[0, cut], np.r_[cut, len(h)] - 1
    i = int(np.argmax(h[ends] - h[starts]))
    return float(h[starts[i]]), float(h[ends[i]])


def plan_sonic_items(sessions: dict, rounds: dict, holds: dict) -> tuple:
    """(items, dropped). `sessions`: sid -> {"side", "view"}; `rounds`: sid -> stored round rows;
    `holds`: sid -> held crop-cache times. Pure: the cadence alone picks the frames, at fixed offsets
    from the start of each selected round's cached span (`cached_span`)."""
    items, dropped = {}, []
    for sid in sorted(sessions):
        if sid not in holds:
            dropped.append({"session_id": sid, "why": "no minimap crop cache"})
            continue
        for r in sorted(rounds.get(sid) or [], key=lambda r: r["round_no"]):
            n = int(r["round_no"])
            if n < SONIC_ROUND_FIRST or (n - SONIC_ROUND_FIRST) % SONIC_ROUND_STRIDE:
                continue
            t0 = float(r["t_start_ms"])
            t1 = float(r["t_end_ms"]) if r.get("t_end_ms") is not None else None
            span = cached_span(holds[sid], t0, t1)
            if span is None:
                dropped.append({"session_id": sid, "round_no": n, "why": "no held sample in the round"})
                continue
            for off in SONIC_OFFSETS_S:
                t = span[0] + off * 1000
                if t > span[1]:
                    dropped.append({"session_id": sid, "round_no": n, "offset_s": off,
                                    "why": f"after the cached span's end ({(span[1] - span[0]) / 1000:.1f} s long)"})
                    continue
                th = nearest(holds[sid], t)
                it = items.setdefault((sid, th), {
                    "key": f"{sid}:{int(round(th))}", "session_id": sid, "t_ms": th, "agent": SONIC_AGENT,
                    "kind": "cadence", "opportunity": [],
                    "t_before_ms": max(span[0], th + SONIC_BEFORE_S * 1000),
                    "view_default": sessions[sid]["view"], "dev_session": False, "near_tuned_label": False,
                    "audit_excluded": False, "pass": "sonic", "deadlock_side": sessions[sid]["side"]})
                it["opportunity"].append({"role": "cadence", "round_no": n, "slot": "Q", "ability": "Sonic Sensor",
                                          "offset_s": off, "t_asked_ms": t, "anchor": "cached_span_start",
                                          "t_round_start_ms": t0, "t_span_ms": list(span),
                                          "round_offset_s": round((th - t0) / 1000, 3)})
    return [items[k] for k in sorted(items)], dropped


def cmd_queue_sonic(args) -> None:
    from reticle import cli
    from reticle.adjudication.identity import side_candidates
    from reticle.lineup import load_lineup
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sonic_square as ss                    # its dev sessions only, recorded at queue time
    qdir = SONIC_QDIR
    out = qdir / SONIC_QUEUE_FILE
    if out.exists():
        raise SystemExit(f"{out} exists; a queue is fixed once built and never overwritten (bump "
                         "SONIC_QUEUE_VERSION and SONIC_QUEUE_FILE for a new one)")
    ss.below_normal()
    dev = set(ss.DEV_LABEL_SESSIONS) | {ss.ROTATED[0]} | set(ss.NEGATIVE_SESSIONS)
    st = Store(str(STORE))
    sessions, rounds, holds, caches, skipped = {}, {}, {}, {}, []
    for man in st.sessions():
        sid = man["session_id"]
        lu = load_lineup(sid, str(STORE))
        if lu is None:
            continue
        sides = sorted(side for side, rows in (lu.get("sides") or {}).items()
                       if SONIC_AGENT in side_candidates(rows)["named"])
        if not sides:
            continue
        minutes = man["n_samples"] / man["sample_hz"] / 60 if man.get("sample_hz") else 0.0
        if sid in dev:
            skipped.append({"session_id": sid, "why": "sonic_square dev session"})
            continue
        if minutes <= SONIC_MIN_MATCH_MIN:
            skipped.append({"session_id": sid, "why": f"capture {minutes:.1f} min, not a match"})
            continue
        player = (lu.get("player") or {}).get("agent")
        view = "self" if player == SONIC_AGENT else ("teammate" if sides == ["ally"] else
                                                     "enemy" if sides == ["enemy"] else "spectator")
        tab = st.read_rounds(sid, cli._date_of(man))
        c, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
        if c is None:
            skipped.append({"session_id": sid, "why": f"no minimap cache ({why})"})
            continue
        sessions[sid] = {"side": "+".join(sides), "view": view, "player_agent": player}
        rounds[sid] = tab.to_pylist() if tab is not None else []
        caches[sid] = c
        holds[sid] = np.asarray(c.holds(), dtype=float)
    items, dropped = plan_sonic_items(sessions, rounds, holds)
    (qdir / "crops").mkdir(parents=True, exist_ok=True)
    by = defaultdict(list)
    for it in items:
        by[it["session_id"]].append(it)
    for sid, its in by.items():
        c = caches[sid]
        x0, y0, x1, y1 = c.rect_of("minimap")
        want = {it["t_ms"] for it in its} | {nearest(holds[sid], max(0.0, it["t_before_ms"])) for it in its}
        got = {s.t_ms: s.frame[y0:y1, x0:x1] for s in c.samples(sorted(want), rois=["minimap"])}
        for it in its:
            tb = nearest(holds[sid], max(0.0, it["t_before_ms"]))
            it["roi"] = [x0, y0, x1, y1]
            it["crop"] = f"crops/{sid}_{int(round(it['t_ms']))}.png"
            it["t_before_held_ms"] = tb
            it["before"] = f"crops/{sid}_{int(round(tb))}.png" if tb != it["t_ms"] else None
            for t, rel in ((it["t_ms"], it["crop"]), (tb, it["before"])):
                if rel and not (qdir / rel).exists():
                    cv2.imwrite(str(qdir / rel), got[t])
    est = len(items) * SECONDS_PER_ITEM / 60
    q = {"version": SONIC_QUEUE_VERSION, "tool": VERSION, "pass": "sonic",
         "built": datetime.datetime.now().isoformat(timespec="seconds"),
         "split": {"all": "heldout for prototypes/sonic_square.py; never tuned on",
                   "excluded_dev_sessions": sorted(dev)},
         "sample": {"opportunities": "match sessions whose stored lineup names Deadlock (lineup.load_lineup, "
                                     "identity.side_candidates)",
                    "min_match_min": SONIC_MIN_MATCH_MIN, "round_first": SONIC_ROUND_FIRST,
                    "round_stride": SONIC_ROUND_STRIDE, "offsets_s": list(SONIC_OFFSETS_S),
                    "offset_anchor": "start of the round's cached span: the longest run of held minimap samples "
                                     "inside the round with every step <= max_gap_ms",
                    "before_s": SONIC_BEFORE_S, "before_clamp": "cached span start", "max_gap_ms": SONIC_MAX_GAP_MS},
         "supersedes": {"file": "queue.json", "version": "sonic-square-heldout-queue-0.1.0", "labelled": False,
                        "why": "offsets from the round start fell in each round's uncached first 11-42 s: "
                               "20 of 23 items at +60 s, 3 at +25 s"},
         "inputs": {"crops": "roi_cache minimap (no decode)", "rounds": "Store.read_rounds"},
         "sessions": sessions, "skipped_sessions": skipped, "dropped": dropped,
         "estimate_min": round(est, 1), "seconds_per_item": SECONDS_PER_ITEM, "items": items}
    if est > BUDGET_MIN:
        raise SystemExit(f"{len(items)} items, ~{est:.0f} min: over the {BUDGET_MIN:.0f} min budget; cap first")
    with open(out, "x", encoding="utf-8", newline="\n") as f:          # "x": never overwrite
        f.write(json.dumps(q, indent=1))
    print(f"{len(items)} items over {len(by)} sessions, ~{est:.0f} min; {len(dropped)} asked frames dropped, "
          f"{len(skipped)} sessions skipped -> {out}")


def session_view(manifest: dict) -> str:
    return "spectator" if "spectator" in (manifest.get("tags") or []) else "self"


def kit(agent: str, cat: dict | None = None) -> list[dict]:
    """The agent's C/Q/E/X in that order, from the tray catalogue, each with its digit."""
    cat = cat or json.load(open(CAT, encoding="utf-8"))["agents"]
    by = {a["key"]: a for a in cat.get(agent, {}).get("abilities", [])}
    out = []
    for s in SLOTS:
        if s in by:
            ic = (by[s].get("icon") or {}).get("file")
            out.append({"digit": str(len(out) + 1), "slot": s, "name": by[s]["name"],
                        "icon": str(STORE / "reference" / ic.replace("\\", "/")) if ic else None})
    return out


# ------------------------------------------------------------------ queue

def cmd_queue(args) -> None:
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import minimap_glyph_eval as ev          # its dev split only, recorded at queue time
    if (QDIR / "queue.json").exists() and not args.rebuild:
        raise SystemExit(f"{QDIR / 'queue.json'} exists; the queue is fixed once built (--rebuild replaces it, "
                         "and only before any label is written)")
    if args.rebuild and answered():
        raise SystemExit(f"{LABEL_DIR} holds answers; a rebuilt queue would move the held-out set under them")
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:  # noqa: BLE001
        pass
    casts = demo_casts()
    drawing = player_drawing(read_jsonl(ANSWERS))
    st = Store(str(STORE))
    caches, holds, views = {}, {}, {}
    for sid in sorted({c["session_id"] for c in casts}):
        man = st.read_manifest(sid)
        views[sid] = session_view(man)
        c, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
        if c is None:
            print(f"{sid}: no minimap cache ({why})")
            continue
        caches[sid] = c
        holds[sid] = np.asarray(c.holds(), dtype=float)
    items, excluded = plan_items(casts, drawing, holds, views, set(ev.DEV), tuned_label_times())
    crops = QDIR / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    by = defaultdict(list)
    for it in items:
        by[it["session_id"]].append(it)
    for sid, its in by.items():
        c = caches[sid]
        x0, y0, x1, y1 = c.rect_of("minimap")
        want = {it["t_ms"] for it in its} | {nearest(holds[sid], max(0.0, it["t_before_ms"])) for it in its}
        got = {s.t_ms: s.frame[y0:y1, x0:x1] for s in c.samples(sorted(want), rois=["minimap"])}
        for it in its:
            tb = nearest(holds[sid], max(0.0, it["t_before_ms"]))
            it["roi"] = [x0, y0, x1, y1]
            it["crop"] = f"crops/{sid}_{int(round(it['t_ms']))}.png"
            it["t_before_held_ms"] = tb
            it["before"] = f"crops/{sid}_{int(round(tb))}.png" if tb != it["t_ms"] else None
            for t, rel in ((it["t_ms"], it["crop"]), (tb, it["before"])):
                if rel and not (QDIR / rel).exists():
                    cv2.imwrite(str(QDIR / rel), got[t])
    est = len(items) * SECONDS_PER_ITEM / 60
    q = {"version": QUEUE_VERSION, "tool": VERSION, "built": datetime.datetime.now().isoformat(timespec="seconds"),
         "split": {"all": "heldout for prototypes/minimap_glyph_eval.py; never tuned on",
                   "report_apart": ["dev_session", "near_tuned_label", "audit_excluded"], "eval_dev_sessions": sorted(ev.DEV),
                   "tuned_window_ms": list(TUNED_WINDOW_MS)},
         "sample": {"opportunities": "labels/demo_cast_class (player-confirmed tray-gated census casts)",
                    "scope": "abilities the player did not answer as drawing nothing or only a shape",
                    "offsets_s": list(OFFSETS_S), "control_s": CONTROL_S, "before_s": BEFORE_S,
                    "audit_s": AUDIT_S, "audit_rule": "one frame per excluded ability, its earliest cast"},
         "inputs": {"crops": "roi_cache minimap (no decode)", "answers": str(ANSWERS.relative_to(STORE))},
         "estimate_min": round(est, 1), "seconds_per_item": SECONDS_PER_ITEM,
         "items": items, "excluded_casts": excluded}
    if est > BUDGET_MIN:
        raise SystemExit(f"{len(items)} items, ~{est:.0f} min: over the {BUDGET_MIN:.0f} min budget; cap first")
    (QDIR / "queue.json").write_text(json.dumps(q, indent=1), encoding="utf-8", newline="\n")
    print(f"{len(items)} items, ~{est:.0f} min; {len(excluded)} casts out of scope -> {QDIR / 'queue.json'}")


def load_queue(qdir=QDIR, name: str = "queue.json") -> dict:
    return json.load(open(Path(qdir) / name, encoding="utf-8"))


def cmd_list(args) -> None:
    q = load_queue(args.qdir, args.queue)
    items = q["items"]
    done = answered(Path(args.labels))
    if q.get("pass") == "sonic":
        print(f"{q['version']}: {len(items)} items ({sum(it['key'] in done for it in items)} answered), "
              f"~{q['estimate_min']} min at {q['seconds_per_item']:.0f} s each")
        print("items per session:", dict(Counter(it["session_id"] for it in items)))
        print("sessions:", q["sessions"])
        print("skipped:", q["skipped_sessions"])
        print("dropped:", dict(Counter(d["why"].split(" ")[0] for d in q["dropped"])))
        return
    per = Counter()
    for it in items:
        for o in it["opportunity"]:
            if o["role"] == "after_cast":
                per[(it["agent"], o["slot"], o["ability"])] += 1
    print(f"{q['version']}: {len(items)} items ({sum(it['key'] in done for it in items)} answered), "
          f"~{q['estimate_min']} min at {q['seconds_per_item']:.0f} s each")
    print("kinds:", dict(Counter(it["kind"] for it in items)),
          "dev_session:", sum(it["dev_session"] for it in items),
          "near_tuned_label:", sum(it["near_tuned_label"] for it in items),
          "audit_excluded:", sum(it.get("audit_excluded", False) for it in items),
          "views:", dict(Counter(it["view_default"] for it in items)))
    ag = Counter(it["agent"] for it in items)
    print(f"\n{len(ag)} agents, {len(per)} abilities (after-cast frames per ability):")
    for (a, s, n), k in sorted(per.items()):
        print(f"  {a:9s} {s} {n:28s} {k}   (agent items {ag[a]})")
    audited = {(o["cast"].split(":")[0], it["agent"], o["slot"]): it["key"] for it in items
               for o in it["opportunity"] if o["role"] == "audit_excluded"}
    print(f"\n{len(q['excluded_casts'])} casts out of scope; the audit frame of each excluded ability:")
    for (a, s, n, w), k in sorted(Counter((e["agent"], e["slot"], e["ability"], e["why"])
                                          for e in q["excluded_casts"]).items()):
        key = next((v for (sid, aa, ss), v in audited.items() if (aa, ss) == (a, s)), "-")
        print(f"  {a:9s} {s} {n:28s} x{k}  audit {key:20s} {w}")


# ------------------------------------------------------------------ answers

def answered(labels=LABEL_DIR) -> dict:
    last = {}
    for f in sorted(glob.glob(str(Path(labels) / "*.jsonl"))):
        for r in read_jsonl(f):
            last[r["key"]] = r
    return last


class Pass:
    """The labeller's state, free of Tk, so the UI, the headless runner and the tests share one path."""

    def __init__(self, items: list[dict], labels: Path, by: str, kits: dict, queue_version: str = QUEUE_VERSION):
        self.labels, self.by, self.kits, self.qv = Path(labels), by, kits, queue_version
        done = answered(self.labels)
        self.todo = [it for it in items if it["key"] not in done]
        self.i, self.marks, self.msg = 0, [], ""

    @property
    def item(self) -> dict | None:
        return self.todo[self.i] if self.i < len(self.todo) else None

    def click(self, x: float, y: float) -> None:
        if self.item is None:
            return
        if self.marks and self.marks[-1]["ability"] is None and not self.marks[-1]["unsure"]:
            self.marks[-1].update(x=float(x), y=float(y))     # an unnamed mark moves rather than stacks
            return
        self.marks.append({"x": float(x), "y": float(y), "ability": None, "other": None, "unsure": False,
                           "view": self.item["view_default"], "view_source": "manifest_tag"})

    def undo(self) -> None:
        if self.marks:
            self.marks.pop()

    def key(self, ch: str, text: str | None = None) -> str:
        """Apply one key; returns 'quit', 'advance', 'back' or ''. `text` answers the 7 = other prompt."""
        ch = (ch or "").lower()
        it = self.item
        self.msg = ""
        if ch in ("q", "escape"):
            return "quit"
        if it is None:
            return ""
        if ch == "a":
            self.i, self.marks = max(0, self.i - 1), []
            return "back"
        last = self.marks[-1] if self.marks else None
        if ch in VIEWS:
            if last:
                last.update(view=VIEWS[ch], view_source="player")
            return ""
        if ch.isdigit():
            if not last:
                self.msg = "click an icon first"
                return ""
            kit = self.kits.get(it["agent"], [])
            hit = [k for k in kit if k["digit"] == ch]
            if hit:
                last.update(ability=f"{it['agent']}:{hit[0]['slot']}", ability_name=hit[0]["name"], unsure=False)
            elif ch in NAMES:
                if ch == "7" and not text:
                    self.msg = "7 needs the answer typed"
                    return ""
                last.update(ability=NAMES[ch], other=text if ch == "7" else None, unsure=False)
            return ""
        if ch == "u":
            if last and last["ability"] is None:
                last.update(unsure=True)
                return ""
            if not self.marks:
                return self._write(nothing=False, unsure=True)
            self.msg = "U names the last mark unsure only while it is unnamed"
            return ""
        if ch == "n":
            if self.marks:
                self.msg = "N means no icon; undo the marks first"
                return ""
            return self._write(nothing=True, unsure=False)
        if ch in ("space", " ", "d"):
            if not self.marks:
                self.msg = "no marks: N for no icon, U for unsure"
                return ""
            if any(m["ability"] is None and not m["unsure"] for m in self.marks):
                self.msg = "name every mark (1-7) or U"
                return ""
            return self._write(nothing=False, unsure=False)
        return ""

    def _write(self, nothing: bool, unsure: bool) -> str:
        it = self.item
        row = {"key": it["key"], "session_id": it["session_id"], "t_ms": it["t_ms"], "agent": it["agent"],
               "kind": it["kind"], "opportunity": it["opportunity"], "marks": self.marks, "nothing": nothing,
               "unsure": unsure, "coords": "minimap roi pixels", "roi": it.get("roi"), "crop": it.get("crop"),
               "split": "heldout", "dev_session": it["dev_session"], "near_tuned_label": it["near_tuned_label"],
               "audit_excluded": it.get("audit_excluded", False),
               "by": self.by, "at": datetime.datetime.now().isoformat(timespec="seconds"), "tool": VERSION,
               "queue_version": self.qv, "compared_against_derived": False}
        if it.get("pass"):           # another pass's item says so; the glyph pass's rows are unchanged
            row.update({"pass": it["pass"], "split": f"heldout:{it['pass']}",
                        "deadlock_side": it.get("deadlock_side")})
        self.labels.mkdir(parents=True, exist_ok=True)
        with open(self.labels / f"{it['session_id']}.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
        self.i, self.marks = self.i + 1, []
        return "advance"


# ------------------------------------------------------------------ UI

def _icon(path: str | None, n: int = 40) -> np.ndarray:
    t = np.full((n, n, 3), 60, np.uint8)
    if not path or not os.path.exists(path):
        return t
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return t
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    if im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    im = cv2.resize(im, (n, n), interpolation=cv2.INTER_AREA if im.shape[0] > n else cv2.INTER_LINEAR)
    a = im[..., 3:4].astype(np.float32) / 255
    return (im[..., :3] * a + 60.0 * (1 - a)).astype(np.uint8)


def run_ui(p: Pass, qdir: Path) -> None:
    import tkinter as tk
    from tkinter import simpledialog

    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title(f"{VERSION}: minimap ability icons (held-out)")
    sh = root.winfo_screenheight()
    top = tk.Frame(root)
    top.pack()
    canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(side="left", padx=4, pady=4)
    side = tk.Frame(top)
    side.pack(side="left", anchor="n", padx=4)
    mag = tk.Label(side, bg="black")
    mag.pack(pady=(4, 2))
    tk.Label(side, text="magnifier (x6, under the cursor)", fg="grey").pack()
    before = tk.Label(side, bg="black")
    before.pack(pady=(10, 2))
    before_cap = tk.Label(side, fg="grey", justify="left")
    before_cap.pack()
    kitrow = tk.Label(root, bg="black")
    kitrow.pack(fill="x", padx=4)
    txt = tk.Label(root, justify="left", anchor="w", font=("Segoe UI", 10), wraplength=1300)
    txt.pack(fill="x", padx=8)
    status = tk.Label(root, anchor="w", fg="grey")
    status.pack(fill="x", padx=8, pady=(0, 4))
    st = {"crop": None, "k": 2.0, "refs": {}, "magxy": None}

    def redraw_marks():
        canvas.delete("mark")
        k = st["k"]
        for j, m in enumerate(p.marks):
            col = "#ffd400" if m["ability"] is None and not m["unsure"] else "#00ff66"
            x, y = m["x"] * k, m["y"] * k
            canvas.create_oval(x - 11 * k / 2, y - 11 * k / 2, x + 11 * k / 2, y + 11 * k / 2, outline=col, width=2,
                               tags="mark")
            lab = "unsure" if m["unsure"] else (m["ability"] or "?")
            canvas.create_text(x + 8 * k, y - 8 * k, text=f"{j + 1} {lab} [{m['view']}]", fill=col, anchor="w",
                               font=("Segoe UI", 9, "bold"), tags="mark")

    def show():
        it = p.item
        if it is None:
            root.destroy()
            return
        crop = cv2.imread(str(qdir / it["crop"]))
        st["crop"] = crop
        h, w = crop.shape[:2]
        k = max(1.0, min(3.0, (sh - 300) / h))
        st["k"] = k
        big = cv2.resize(crop, (int(w * k), int(h * k)), interpolation=cv2.INTER_NEAREST)   # display only
        st["refs"]["main"] = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)))
        canvas.configure(width=big.shape[1], height=big.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, image=st["refs"]["main"], anchor="nw")
        if it.get("before"):
            b = cv2.imread(str(qdir / it["before"]))
            b = cv2.resize(b, (b.shape[1] // 2, b.shape[0] // 2), interpolation=cv2.INTER_AREA)
            st["refs"]["before"] = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(b, cv2.COLOR_BGR2RGB)))
            before.configure(image=st["refs"]["before"])
            lead = (f"{(it['t_ms'] - it['t_before_held_ms']) / 1000:.0f} s before" if it.get("pass")
                    else "1 s before the cast")
            before_cap.configure(text=f"{lead} ({it['t_before_held_ms'] / 1000:.2f} s), half size,\n"
                                      "for comparison only; mark on the left")
        else:
            before.configure(image="")
            before_cap.configure(text="")
        cells = []
        for kk in p.kits.get(it["agent"], []):
            c = _icon(kk["icon"])
            bar = np.full((c.shape[0], 190, 3), 0, np.uint8)
            cv2.putText(bar, f"{kk['digit']} = {kk['slot']} {kk['name']}"[:28], (4, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (255, 255, 255), 1, cv2.LINE_AA)
            cells.append(np.hstack([c, bar]))
        if cells:
            row = np.hstack(cells)
            st["refs"]["kit"] = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(row, cv2.COLOR_BGR2RGB)))
            kitrow.configure(image=st["refs"]["kit"])
        why = "; ".join(f"{o['role']} {o['slot']} {o['ability']} {o['offset_s']:+.0f} s" for o in it["opportunity"])
        if it.get("pass") == "sonic":
            why = "; ".join(f"round {o['round_no']} start {o['offset_s']:+.0f} s" for o in it["opportunity"])
            txt.configure(text=(f"{it['session_id']} (match; the lineup puts Deadlock on: {it['deadlock_side']}) at "
                                f"{it['t_ms'] / 1000:.2f} s. Default view: {it['view_default']}.\n{SONIC_TEXT}\n"
                                f"Why this frame (a fixed cadence, not a detection): {why}"))
            redraw_marks()
            set_status()
            return
        txt.configure(text=(
            f"{it['session_id']} ({it['agent']} demo) at {it['t_ms'] / 1000:.2f} s. Default view: {it['view_default']}.\n"
            "Click the centre of EVERY ability icon on the minimap (whoever cast it; not shapes, portraits, pings "
            "or the spike), then name it: 1-4 kit as below (this agent's smoke too); 5 smoke of an unknown caster; "
            "6 another agent's ability; 7 other (type).\n"
            "U = last mark unsure (or the whole item, with no marks); Z/X/C/V = last mark's view self/teammate/"
            "enemy/spectator; right-click undo; SPACE/D save; N = no ability icon; A back; Q/ESC quit.\n"
            f"Why this frame (an opportunity, not a detection): {why}"))
        redraw_marks()
        set_status()

    def set_status():
        it = p.item
        if it is None:
            return
        status.configure(text=f"{p.i + 1} / {len(p.todo)} unanswered   {it['key']}   marks {len(p.marks)}   "
                              f"{p.msg}")

    def magnify(e):
        if st["crop"] is None:
            return
        k = st["k"]
        x, y = int(e.x / k), int(e.y / k)
        if st["magxy"] == (x, y):
            return
        st["magxy"] = (x, y)
        R = 16
        pad = cv2.copyMakeBorder(st["crop"], R, R, R, R, cv2.BORDER_CONSTANT)
        win = pad[y:y + 2 * R, x:x + 2 * R]
        big = cv2.resize(win, (2 * R * 6, 2 * R * 6), interpolation=cv2.INTER_NEAREST)   # display only
        cv2.drawMarker(big, (R * 6 + 3, R * 6 + 3), (0, 255, 0), cv2.MARKER_CROSS, 14, 1)
        st["refs"]["mag"] = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)))
        mag.configure(image=st["refs"]["mag"])

    def on_click(e):
        p.click(e.x / st["k"], e.y / st["k"])
        redraw_marks()
        set_status()

    def on_undo(_e):
        p.undo()
        redraw_marks()
        set_status()

    def on_key(e):
        ch = "escape" if e.keysym == "Escape" else ("space" if e.keysym == "space" else (e.char or ""))
        text = None
        if ch == "7" and p.marks:
            text = simpledialog.askstring("other", "The ability, in words:", parent=root)
            if not text:
                return
        r = p.key(ch, text)
        if r == "quit":
            root.destroy()
        elif r in ("advance", "back"):
            show()
        else:
            redraw_marks()
            set_status()

    canvas.bind("<Button-1>", on_click)
    canvas.bind("<Button-3>", on_undo)
    canvas.bind("<Motion>", magnify)
    root.bind("<Key>", on_key)
    show()
    root.mainloop()


def run_headless(p: Pass, script: list) -> None:
    """Feed events through the same state machine the UI drives: ["click", x, y], ["key", ch] or
    ["key", "7", "text"], ["undo"]."""
    for ev in script:
        if p.item is None:
            break
        if ev[0] == "click":
            p.click(ev[1], ev[2])
        elif ev[0] == "undo":
            p.undo()
        elif p.key(ev[1], ev[2] if len(ev) > 2 else None) == "quit":
            break
        if p.msg:
            print("  msg:", p.msg)


def cmd_label(args) -> None:
    q = load_queue(args.qdir, args.queue)
    cat = json.load(open(CAT, encoding="utf-8"))["agents"]
    kits = {a: kit(a, cat) for a in {it["agent"] for it in q["items"]}}
    p = Pass(q["items"], Path(args.labels), args.by, kits, q["version"])
    if not p.todo:
        print(f"all {len(q['items'])} items answered ({args.labels})")
        return
    if args.headless:
        run_headless(p, json.load(open(args.headless, encoding="utf-8")))
    else:
        run_ui(p, Path(args.qdir))
    done = answered(Path(args.labels))
    print(f"{sum(it['key'] in done for it in q['items'])} / {len(q['items'])} answered -> {args.labels}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pass", dest="pass_", choices=("glyph", "sonic"), default="glyph",
                    help="glyph: the minimap glyph pass (default); sonic: the Sonic Sensor match pass")
    sub = ap.add_subparsers(dest="cmd")
    qp = sub.add_parser("queue")
    qp.add_argument("--rebuild", action="store_true")
    lp = sub.add_parser("list")
    lp.add_argument("--labels", default=None)
    lb = sub.add_parser("label")
    lb.add_argument("--by", default="player")
    lb.add_argument("--labels", default=None)
    lb.add_argument("--headless", help="a JSON list of events to feed instead of the window")
    for sp in (lp, lb):
        sp.add_argument("--queue", default=None, help=f"queue file in the pass's directory (sonic default: "
                                                      f"{SONIC_QUEUE_FILE}; glyph: queue.json)")
    args = ap.parse_args()
    if not args.cmd:
        args = ap.parse_args(sys.argv[1:] + ["label"])
    sonic = args.pass_ == "sonic"
    args.qdir = str(SONIC_QDIR if sonic else QDIR)
    if getattr(args, "queue", None) is None:
        args.queue = SONIC_QUEUE_FILE if sonic else "queue.json"
    if args.cmd in ("list", "label") and args.labels is None:
        args.labels = str(SONIC_LABEL_DIR if sonic else LABEL_DIR)
    {"queue": cmd_queue_sonic if sonic else cmd_queue, "list": cmd_list, "label": cmd_label}[args.cmd](args)


if __name__ == "__main__":
    main()
