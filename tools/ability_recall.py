r"""Recall of unnamed ability entities, scored against the player's exhaustive labels.

    .\.venv\Scripts\python.exe tools\ability_recall.py --select
    .\.venv\Scripts\python.exe tools\ability_recall.py [--out DIR]

Stage 4 of `docs/ABILITY_DETECTION.md` (sections 10 and 11, pass 1).

**Select** (`--select`) fixes the frames before any ability pass runs. For
each session of `SESSIONS` it builds the shape reader exactly as `reticle
scan SID --only ability --from cache` builds it, clips its spans to the
minimap crop cache's rounds (`roi_cache.choose_source`) and takes the pass's
own 2 Hz grid (`passes.cache_feed`). A sample is live where `gametime` puts
it in a live phase (`ability_scan.LIVE_PHASES`), the reader's own test.
Every CADENCE-th live sample, from the first, is a frame. It reads the
cache's index and the stored rounds only: nothing is decoded and no pixel is
read, so the choice cannot rest on what the pass will find. The list goes to
the store's `labels/ability_recall_20260930/selection/<sid>.json`.

**Score** (the default) reads the player's answers from
`labels/ability_recall_20260930/<sid>.jsonl` (the last row for a time wins;
`prototypes/label_ability_recall.py` writes them) and the stored
`ability_icon` and `ability_shape_scan` streams. Per widget size it prints:

- *Entity recall.* Marks are linked into entities (`entities`): one kind,
  within LINK_PX (scaled to the widget) on consecutive selected frames of one
  round, or the same free-text name in one round. An entity is found when a
  proposal explains any of its marks. The one-sided 95% Clopper-Pearson
  lower bound goes beside it (`cp_lower`). Until stage 5 builds tracks, a
  proposal on a labelled frame stands for the track that would cover it.
- *Frame recall.* The share of target marks a proposal on the same frame
  explains.
- *Specificity.* Proposals on a labelled frame that explain no mark, per
  frame, by proposal type, over every labelled frame and over the frames the
  player answered "nothing here".
- *Misses* as surprise rows (`misses.jsonl` in `--out`): each unexplained
  target mark, with the stream's reason at that time and the nearest
  proposal.

What counts. Smokes stay out of the recall target and keep their own lane
(section 17, answer 4), and so do marks of kind `unsure`; both still explain
proposals, so a proposer's hit on a smoke is not charged to specificity. A
frame the player answered unsure is out of every count. A proposal is an
icon candidate of `ability_icon` (every stored candidate: the proposer's
output is the candidate set the tracker will read), or a ring or beam of
`ability_shape_scan` whose owner accepted it (`--all-shapes` adds the
rejected ones). Explaining (`explains`): an icon explains a mark within its
radius plus TOL_PX of its centre; a ring, a mark within TOL_PX or a quarter
of its radius of its centre, or within TOL_PX of its rim; a beam, a mark
within TOL_PX of its segment. The player marks an icon, ring or area at its
centre and a line anywhere along it.

Not for. Naming (pass 2), tracks (stage 5), or smokes (`tools/smoke_identity.py`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOOL = "ability-recall-0.1.0"
SET = "ability_recall_20260930"
#: Every CADENCE-th live 2 Hz sample is a frame (section 10, fixed in advance).
CADENCE = 20
#: The chosen sessions per widget size, in blocks: label block 1 whole, then
#: block 2 whole if block 1 holds fewer than MIN_ENTITIES entities; stop at
#: the end of a block, never at a count (section 10).
SESSIONS = {
    331: (("043bafca271a", 1), ("59c70f1ef720", 2)),
    465: (("c62c2b06bcfb", 1), ("587c15b07779", 2)),
}
MIN_ENTITIES = 60
#: Mark kinds the player can give; the recall target leaves out NOT_TARGET.
KINDS = ("icon", "ring", "line", "area", "smoke", "unsure")
NOT_TARGET = ("smoke", "unsure")
#: Explaining tolerance, px of the crop.
TOL_PX = 3.0
#: Marks of one kind this close (px at 465, scaled) on consecutive frames of a
#: round are one entity.
LINK_PX = 6.0
ALPHA = 0.05


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def set_dir(store: Path) -> Path:
    return store / "labels" / SET


# --- statistics -----------------------------------------------------------------

def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                                 + i * lp + (n - i) * lq) for i in range(k, n + 1)))


def cp_lower(k: int, n: int, alpha: float = ALPHA) -> float | None:
    """The one-sided (1 - alpha) Clopper-Pearson lower bound on a rate from
    k of n: the p at which P(X >= k) = alpha. None for n = 0."""
    if n <= 0:
        return None
    if k <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _binom_sf(k, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --- labels ---------------------------------------------------------------------

def load_answers(path: Path) -> dict[float, dict]:
    """The answer per frame time; the last row for a time wins."""
    out: dict[float, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[float(r["t_ms"])] = r
    return out


def entities(frames: list[dict], answers: dict[float, dict], scale: float = 1.0) -> list[dict]:
    """Target marks linked into entities.

    `frames` are a session's selected frames in order (`t_ms`, `index` (the
    position in the selection), `round_no`); `answers` the player's rows by
    time. Two target marks are one entity when they share a kind and lie
    within LINK_PX x `scale` on frames `index` k and k + 1 of one round, or
    carry the same non-empty name in one round. Returns entities as
    {"id", "kind", "round_no", "marks": [(t_ms, mark)]}."""
    marks = []
    for f in frames:
        a = answers.get(float(f["t_ms"]))
        if a is None or a.get("answer") != "marks":
            continue
        for m in a.get("marks") or ():
            if m.get("kind") in NOT_TARGET:
                continue
            marks.append((f, m))
    parent = list(range(len(marks)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    link = LINK_PX * scale
    for i, (fi, mi) in enumerate(marks):
        for j in range(i + 1, len(marks)):
            fj, mj = marks[j]
            if fi.get("round_no") != fj.get("round_no"):
                continue
            ni, nj = (mi.get("name") or "").strip().lower(), (mj.get("name") or "").strip().lower()
            same_name = bool(ni) and ni == nj
            near = (mi["kind"] == mj["kind"] and abs(fi["index"] - fj["index"]) == 1
                    and math.hypot(mi["x"] - mj["x"], mi["y"] - mj["y"]) <= link)
            if same_name or near:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(marks)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for n, idx in enumerate(sorted(groups.values(), key=lambda g: g[0])):
        f0, m0 = marks[idx[0]]
        out.append({"id": n, "kind": m0["kind"], "round_no": f0.get("round_no"),
                    "marks": [(float(marks[i][0]["t_ms"]), marks[i][1]) for i in idx]})
    return out


# --- proposals ------------------------------------------------------------------

def proposals(icon_row: dict | None, shape_row: dict | None, all_shapes: bool = False) -> list[dict]:
    """The proposals stored for one sample: icon candidates, and the accepted
    rings and beam (every ring and the beam with `all_shapes`)."""
    out = []
    for c in (icon_row or {}).get("candidates") or ():
        out.append({"type": "icon", "cx": float(c["cx"]), "cy": float(c["cy"]), "r": float(c["r"])})
    if shape_row:
        for g in shape_row.get("rings") or ():
            if all_shapes or g.get("accepted"):
                out.append({"type": "ring", "cx": float(g["cx"]), "cy": float(g["cy"]),
                            "r": float(g["r"])})
        b = shape_row.get("beam")
        if b and (all_shapes or b.get("accepted")):
            out.append({"type": "beam", "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"]})
    return out


def distance(mark: dict, p: dict) -> float:
    """How far a mark lies outside what proposal `p` explains, in px (0 or
    less is inside the tolerance's reach before TOL_PX)."""
    x, y = float(mark["x"]), float(mark["y"])
    if p["type"] == "icon":
        return math.hypot(x - p["cx"], y - p["cy"]) - p["r"]
    if p["type"] == "ring":
        d = math.hypot(x - p["cx"], y - p["cy"])
        return min(d - max(0.0, 0.25 * p["r"] - TOL_PX), abs(d - p["r"]))
    ax, ay, bx, by = p["x0"], p["y0"], p["x1"], p["y1"]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def explains(mark: dict, p: dict) -> bool:
    return distance(mark, p) <= TOL_PX


# --- scoring --------------------------------------------------------------------

def score_session(sid: str, frames: list[dict], answers: dict[float, dict], icon_rows: dict,
                  shape_rows: dict, scale: float, all_shapes: bool = False) -> dict:
    """Counts for one session, and its miss rows.

    `icon_rows` and `shape_rows` map a stored sample time to its row; a
    frame with no icon row has no proposals, and its misses say so."""
    labelled = [f for f in frames if float(f["t_ms"]) in answers
                and answers[float(f["t_ms"])].get("answer") in ("marks", "nothing")]
    props = {float(f["t_ms"]): proposals(icon_rows.get(float(f["t_ms"])),
                                         shape_rows.get(float(f["t_ms"])), all_shapes)
             for f in labelled}
    ents = entities(labelled, answers, scale)
    misses, found, mk_n, mk_hit = [], 0, 0, 0
    for e in ents:
        hit = False
        for t, m in e["marks"]:
            mk_n += 1
            ok = any(explains(m, p) for p in props[t])
            mk_hit += ok
            hit |= ok
        found += hit
        if not hit:
            for t, m in e["marks"]:
                row = icon_rows.get(t)
                near = min(((distance(m, p), p["type"]) for p in props[t]), default=None)
                misses.append({"kind": "surprise", "surprise": "ability_recall_miss",
                               "session_id": sid, "t_ms": t, "entity": e["id"],
                               "round_no": e["round_no"], "x": m["x"], "y": m["y"],
                               "mark_kind": m["kind"], "name": m.get("name"),
                               "stream_reason": ("no_row" if row is None else row.get("reason")),
                               "nearest": None if near is None else
                               {"px": round(near[0], 1), "type": near[1]}})
    unexplained = {"icon": 0, "ring": 0, "beam": 0}
    nothing_frames, nothing_unexplained = 0, 0
    for f in labelled:
        t = float(f["t_ms"])
        a = answers[t]
        ms = a.get("marks") or () if a.get("answer") == "marks" else ()
        n_un = 0
        for p in props[t]:
            if not any(explains(m, p) for m in ms):
                unexplained[p["type"]] += 1
                n_un += 1
        if a.get("answer") == "nothing":
            nothing_frames += 1
            nothing_unexplained += n_un
    return {"session_id": sid, "frames": len(frames), "labelled": len(labelled),
            "unsure_frames": sum(1 for f in frames
                                 if answers.get(float(f["t_ms"]), {}).get("answer") == "unsure"),
            "entities": len(ents), "found": found, "marks": mk_n, "marks_hit": mk_hit,
            "unexplained": unexplained, "nothing_frames": nothing_frames,
            "nothing_unexplained": nothing_unexplained, "misses": misses}


def combine(parts: list[dict]) -> dict:
    """One widget size's totals from its sessions' counts."""
    n = sum(p["entities"] for p in parts)
    k = sum(p["found"] for p in parts)
    mn, mh = sum(p["marks"] for p in parts), sum(p["marks_hit"] for p in parts)
    fr = sum(p["labelled"] for p in parts)
    un = {t: sum(p["unexplained"][t] for p in parts) for t in ("icon", "ring", "beam")}
    nf = sum(p["nothing_frames"] for p in parts)
    nu = sum(p["nothing_unexplained"] for p in parts)
    return {"sessions": [p["session_id"] for p in parts], "frames_labelled": fr,
            "entities": n, "found": k, "entity_recall": (k / n) if n else None,
            "entity_recall_lower95": cp_lower(k, n),
            "marks": mn, "marks_hit": mh, "frame_recall": (mh / mn) if mn else None,
            "unexplained_per_frame": {t: (v / fr) if fr else None for t, v in un.items()},
            "unexplained_per_frame_all": (sum(un.values()) / fr) if fr else None,
            "nothing_frames": nf,
            "unexplained_per_nothing_frame": (nu / nf) if nf else None,
            "misses": sum(len(p["misses"]) for p in parts)}


# --- selection ------------------------------------------------------------------

def select_session(store, sid: str) -> dict:
    """The fixed frames of one session: every CADENCE-th live sample of the
    ability pass's own 2 Hz grid over the minimap crop cache."""
    from reticle import gametime, stalls
    from reticle.ability_scan import LIVE_PHASES, shape_reader
    from reticle.cli import _active_spans, _date_of, _live_round_spans
    from reticle.minimap import minimap_roi_px
    from reticle.passes import SessionContext, cache_feed
    from reticle.profiles import get_profile
    from reticle.roi_cache import choose_source, declare_set

    man = store.read_manifest(sid)
    dur_min = float(man["source"]["duration_ms"]) / 60000.0
    if dur_min <= 15.0:
        raise SystemExit(f"{sid}: {dur_min:.1f} min is not a match (needs > 15)")
    date = _date_of(man)
    profile = get_profile(man["source_profile"])
    spans = _active_spans(store, sid, date)
    ctx = SessionContext(store=store, manifest=man, profile=profile, spans=spans)
    bp = shape_reader(ctx, spans)
    declare_set(bp, "minimap", profile, ctx.wh)

    def live_rounds():
        try:
            return _live_round_spans(store, sid, date), None
        except SystemExit as exc:
            return None, str(exc)
    cache, why, _notes = choose_source(store.root, man, profile, [bp], "cache", live_rounds)
    if cache is None:
        raise SystemExit(f"{sid}: no minimap crop cache feeds the ability pass ({why}); "
                         f"drop it, never decode")
    every, _want = cache_feed([bp], cache)
    rs, hud = store.read_rounds(sid, date), store.read_hud(sid, date)
    gt = gametime.build_session_gametime(sid, hud, rs.to_pylist(),
                                         stall_list=stalls.for_session(store, sid, date))
    live = []
    for t in every:
        g = gt.game_time_at(float(t))
        if g.phase in LIVE_PHASES:
            live.append((float(t), int(g.round_no), g.phase))
    picked = live[::CADENCE]
    box = minimap_roi_px(profile, *ctx.wh)
    return {"session_id": sid, "set": SET, "tool": TOOL, "cadence": CADENCE,
            "grid_hz": bp.hz, "live_phases": list(LIVE_PHASES), "live_samples": len(live),
            "widget_px": int(box[2] - box[0]), "roi": [int(v) for v in box],
            "capture": man["source"]["path"], "duration_min": round(dur_min, 1),
            "cache": cache.record["version"], "spans_clip": getattr(bp, "spans_clip", None),
            "selected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "frames": [{"index": i, "t_ms": t, "round_no": r, "phase": ph}
                       for i, (t, r, ph) in enumerate(picked)]}


def load_selection(store_root: Path, sid: str) -> dict | None:
    p = set_dir(store_root) / "selection" / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _by_t(rows: list[dict]) -> dict[float, dict]:
    return {float(r["t_ms"]): r for r in rows if r.get("kind") == "frame"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(Path.home() / "reticle-store"))
    ap.add_argument("--select", action="store_true", help="fix the frames (no decode, no pixels)")
    ap.add_argument("--force", action="store_true", help="with --select, overwrite a selection")
    ap.add_argument("--labels", help="the answers directory (default the set's)")
    ap.add_argument("--all-shapes", action="store_true", help="count rejected rings and beams too")
    ap.add_argument("--out", help="where misses.jsonl and summary.json go")
    args = ap.parse_args(argv)
    below_normal()
    from reticle.store import Store
    store = Store(args.store)
    root = Path(args.store)
    sessions = [(w, sid, blk) for w, ss in SESSIONS.items() for sid, blk in ss]

    if args.select:
        d = set_dir(root) / "selection"
        d.mkdir(parents=True, exist_ok=True)
        for w, sid, blk in sessions:
            p = d / f"{sid}.json"
            if p.exists() and not args.force:
                print(f"{sid}: selection exists, kept ({p})")
                continue
            sel = select_session(store, sid)
            if sel["widget_px"] != w:
                raise SystemExit(f"{sid}: widget {sel['widget_px']} px, listed under {w}")
            sel["block"] = blk
            p.write_text(json.dumps(sel, indent=1), encoding="utf-8")
            print(f"{sid}  {w} px  block {blk}  {sel['live_samples']} live samples -> "
                  f"{len(sel['frames'])} frames  {sel['capture']}")
        return 0

    lab = Path(args.labels) if args.labels else set_dir(root)
    out_dir = Path(args.out) if args.out else (
        root / "analysis" / f"ability-recall-{datetime.now().strftime('%Y%m%d')}")
    summary, all_misses = {}, []
    for w in SESSIONS:
        parts = []
        for ww, sid, blk in sessions:
            if ww != w:
                continue
            sel = load_selection(root, sid)
            answers = load_answers(lab / f"{sid}.jsonl")
            if sel is None or not answers:
                print(f"{sid}: {'no selection' if sel is None else 'no answers'}; skipped")
                continue
            icon = store.read_events("ability_icon", sid)
            shape = store.read_events("ability_shape_scan", sid)
            if not icon:
                print(f"{sid}: no ability_icon stream; run reticle scan {sid} --only ability "
                      f"--from cache; skipped")
                continue
            part = score_session(sid, sel["frames"], answers, _by_t(icon), _by_t(shape),
                                 scale=w / 465.0, all_shapes=args.all_shapes)
            part["block"] = blk
            parts.append(part)
            all_misses.extend(part["misses"])
        if not parts:
            continue
        s = combine(parts)
        summary[str(w)] = s
        lb = s["entity_recall_lower95"]
        print(f"{w} px  sessions {', '.join(s['sessions'])}  frames {s['frames_labelled']}")
        print(f"  entity recall {s['found']}/{s['entities']}"
              + ("" if s["entity_recall"] is None else
                 f" = {s['entity_recall']:.3f}, one-sided 95% lower bound {lb:.3f}"))
        if s["entities"] < MIN_ENTITIES:
            print(f"  fewer than {MIN_ENTITIES} entities: label the next block whole")
        if s["frame_recall"] is not None:
            print(f"  frame recall {s['marks_hit']}/{s['marks']} = {s['frame_recall']:.3f}")
        up = s["unexplained_per_frame"]
        print("  unexplained proposals per frame: "
              + "  ".join(f"{t} {v:.2f}" for t, v in up.items() if v is not None)
              + (f"; per 'nothing' frame {s['unexplained_per_nothing_frame']:.2f}"
                 if s["unexplained_per_nothing_frame"] is not None else ""))
        print(f"  misses {s['misses']} rows")
    if not summary:
        print("no labelled session to score")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "misses.jsonl").open("w", encoding="utf-8") as fh:
        for m in all_misses:
            fh.write(json.dumps(m) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(
        {"tool": TOOL, "set": SET, "tol_px": TOL_PX, "link_px": LINK_PX,
         "all_shapes": bool(args.all_shapes), "by_widget": summary}, indent=1), encoding="utf-8")
    print(f"misses and summary -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
