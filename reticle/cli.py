"""Reticle ingestion CLI.

    reticle synth   [--out PATH]              make a synthetic clip to test with
    reticle probe   VIDEO                     fingerprint + render ROI overlays
    reticle ingest  VIDEO                     decode -> L1 primitives -> parquet
    reticle segment SESSION|--all             recompute spans from stored L1
    reticle inspect [SESSION]                 what is in the store
    reticle frames  SESSION --every N         dump frames for eyeballing
    reticle hud     [SESSION]                 stage 02: read the scoreline
    reticle minimap [SESSION]                 stage 02: player position off the minimap
    reticle glyphs  VIDEO                     mine digit templates from footage
    reticle verify  [SESSION]                 check HUD reads against domain invariants
    reticle overlay [SESSION]                 render detections onto the video
    reticle kd      [SESSION]                 running K/D per round, to check against the scoreboard
    reticle board   [SESSION]                 read the Tab scoreboard and score our K/D against it
    reticle economy FACTS.json                apply explicit facts to the credit ledger
    reticle ability-coverage                  inventory ability evidence without decoding
    reticle ability-timeline                  build bounded ability-use claims
    reticle ability-entities                  build alternative ability entity hypotheses
    reticle ability-gallery                   appearance galleries + held-out identity scores
    reticle ability-capture                   targeted capture queue for demonstrated gaps
    reticle ability-phases                    entity phases and their transition causes
    reticle acquisition-plan SPEC.json        validate and plan evidence sampling
    reticle capabilities                      validated reader tiers, and what is withheld
    reticle fidelity-check                    P3: cheaper tiers vs reference fidelity
    reticle status  [--write]                 generated pipeline status -> STATUS.md
    reticle sql     "SELECT ..."              DuckDB over the store
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from collections import Counter
import sys
import time
from pathlib import Path

import numpy as np

from .decode import sample_frames, sample_multi, sample_spans
from .checks import KNOWN_KD, check_hud, player_events, track_entries
from .rounds import build_rounds, summarise
from .scoreboard import ScoreboardReader, read_scoreboard
from . import cone, geometry, lighting
from .fidelity import FROZEN_WINDOWS
from .fingerprint import fingerprint
from .killfeed import (KILLFEED_PORTRAIT_VERSION, KillfeedPortraitReader,
                       KillfeedRead, analyse_killfeed, killfeed_roi,
                       me_template_path, overlay_mask, read_killfeed)
from .belief import (BELIEF_VERSION, absent_instants, resolve,
                     round_voids)
from .minimap import (ALLY_DESCRIPTOR_HZ, FIT_ERR_PX, MAX_ALLIES, AllyIconReader, _odd,
                      ally_rings, art_floor,
                      filter_track, floor_mask, minimap_roi_px, slab_mask,
                      widget_scale,
                      pick_self, self_icons, widget_drawn)
from .overlay import OverlayContext, draw
from .passes import SessionContext, run as passes_run
from .ping import LIFETIME_S, PingReader
from .lineup import LineupReader
from .roster import RosterReader
from . import stalls
from . import gametime
from .ocr import (GLYPH_H, GLYPH_W, Templates, cluster_glyphs, crop_gray,
                  read_bottom_hud, read_scoreline, scoreline_roi, segment_glyphs)
from .primitives import PrimitiveExtractor
from .profiles import DEFAULT_PROFILE, MinimapMode, get_profile
from .segment import HUD_CHROME_ROIS, STATES, SegmentConfig, classify, segment
from .store import DEFAULT_STORE, Store
from .version import (ALLY_ICON_VERSION, EXTRACTOR_VERSION, HUD_VERSION, MINIMAP_VERSION, PING_VERSION,
                      ROSTER_VERSION, SCOREBOARD_VERSION, SEGMENTER_VERSION)
from .hud_reader import HudReader

_HudPass = HudReader


def _fmt_ms(ms: float) -> str:
    s = max(0.0, ms) / 1000.0
    return f"{int(s // 60):d}:{s % 60:04.1f}"


def _fmt_hms(ms: float) -> str:
    s = int(max(0.0, ms) // 1000)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _date_of(manifest: dict) -> str:
    return manifest["ingested_at"][:10]


def _dividers(table, column: str):
    """The packed divider column, or None on a session stored without one.

    Sessions read before hud-0.8.0 carry no divider, and `track_entries` falls
    back to slot and time for them rather than refusing to score them at all.
    """
    return table.column(column).to_pylist() if column in table.column_names else None


def _resolve_session(store: Store, session: str | None) -> dict:
    sessions = store.sessions()
    if not sessions:
        raise SystemExit(f"store is empty: {store.root}\nrun `reticle ingest <video>` first")
    if session is None:
        if len(sessions) == 1:
            return sessions[0]
        ids = ", ".join(s["session_id"] for s in sessions)
        raise SystemExit(f"store holds {len(sessions)} sessions; name one of: {ids}")
    matches = [s for s in sessions if s["session_id"].startswith(session)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(f"ambiguous session prefix {session!r}: "
                         + ", ".join(s["session_id"] for s in matches))
    raise SystemExit(f"no session matching {session!r} in {store.root}")


# --------------------------------------------------------------------------- synth

def cmd_synth(args) -> int:
    from .synth import generate

    out = Path(args.out) if args.out else Path.cwd() / "synthetic_capture"
    print("rendering synthetic capture (plumbing fixture, not a simulation)...")
    path, script = generate(out, width=args.width, height=args.height, fps=args.fps)
    total = sum(sec for _, sec in script)
    print(f"  wrote      {path}")
    print(f"  {args.width}x{args.height} @ {args.fps:g}fps, {total}s")
    print(f"  script     {' '.join(f'{s}:{n}s' for s, n in script)}")
    print(f"\nnext: reticle ingest \"{path}\"")
    return 0


# --------------------------------------------------------------------------- probe

def cmd_probe(args) -> int:
    import cv2

    fp = fingerprint(args.video)
    profile = get_profile(args.profile)

    print(f"source     {fp.filename}")
    print(f"  size     {fp.size_bytes / 1e9:.2f} GB")
    print(f"  frame    {fp.width}x{fp.height}  ({fp.aspect})")
    print(f"  fps      {fp.fps or float('nan'):.3f}" + ("" if fp.fps else "   <- container reported none"))
    print(f"  frames   {fp.frame_count or 'unknown'}")
    print(f"  duration {_fmt_hms(fp.duration_ms) if fp.duration_ms else 'unknown'}")
    print(f"  content  {fp.content_key}")
    print(f"  session  {fp.session_id}")
    print(f"  profile  {profile.name}")
    print(f"  minimap  {profile.minimap}")

    if fp.aspect != profile.aspect:
        print(f"\n  ! frame is {fp.aspect} but profile {profile.name} expects "
              f"{profile.aspect}; ROI boxes will not line up")

    out_dir = Path(args.out) if args.out else Path.cwd() / f"probe_{fp.session_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(fp.path)
    total = fp.frame_count if fp.frame_count > 0 else 0
    written = 0
    try:
        for i in range(args.n):
            if total:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / args.n))
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            canvas = frame.copy()
            for roi in profile.rois:
                x0, y0, x1, y1 = roi.pixels(fp.width, fp.height)
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 220, 255), 2)
                cv2.putText(canvas, roi.name, (x0 + 4, max(16, y0 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1, cv2.LINE_AA)
            path = out_dir / f"probe_{i:02d}_{int(t_ms):08d}ms.jpg"
            cv2.imwrite(str(path), canvas)
            written += 1
    finally:
        cap.release()

    if profile.overlay_zones:
        print()
        for zone in profile.overlay_zones:
            hit = [r.name for r in profile.rois if zone.hits(r)]
            zx = zone.pixels(fp.width, fp.height)
            print(f"  overlay  {zone.name:12s} {zx}  "
                  + (f"can obscure: {', '.join(hit)}" if hit else "clears every ROI"))

    print(f"\nwrote {written} annotated frames to {out_dir}")
    print("open them and check each box lands on the right HUD element.")
    print("if not, edit the fractions in reticle/profiles.py and re-run probe.")
    return 0


# --------------------------------------------------------------------------- ingest

def cmd_ingest(args) -> int:
    store = Store(args.store)
    fp = fingerprint(args.video)
    profile = get_profile(args.profile)
    minimap = MinimapMode.parse(args.minimap_mode) if args.minimap_mode else profile.minimap
    date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    existing = next((s for s in store.sessions() if s["session_id"] == fp.session_id), None)
    if existing and not args.force:
        d = _date_of(existing)
        if store.has_primitives(fp.session_id, d):
            print(f"cache hit  session {fp.session_id} already has L1 at {EXTRACTOR_VERSION}")
            print(f"           {store.primitives_path(fp.session_id, d)}")
            print("           pass --force to re-decode")
            return 0
    if existing:
        date = _date_of(existing)

    print(f"session    {fp.session_id}  ({fp.filename})")
    print(f"source     {fp.width}x{fp.height} @ {fp.fps:.2f}fps, "
          f"{_fmt_hms(fp.duration_ms) if fp.duration_ms else 'unknown length'}")
    print(f"profile    {profile.name}")
    print(f"minimap    {minimap}" + ("" if minimap.has_static_homography
          else "   <- no single session-wide minimap->world transform"))
    print(f"sampling   {args.hz:g} Hz  (extractor {EXTRACTOR_VERSION})")
    if not fp.fps:
        print("           ! container reported no fps -- decoding every frame")

    extractor = PrimitiveExtractor(profile, fp.width, fp.height)
    rows: list[dict] = []
    t0 = time.perf_counter()
    last_report = t0

    for s in sample_frames(fp.path, args.hz, fp.fps, args.max_frames):
        rows.append(extractor.process(s.frame, s.frame_idx, s.t_ms))
        now = time.perf_counter()
        if now - last_report >= 2.0:
            covered = s.t_ms / fp.duration_ms if fp.duration_ms else 0.0
            rate = len(rows) / (now - t0)
            msg = f"\r  {len(rows):>7d} samples  {_fmt_hms(s.t_ms)}  {rate:5.1f} samp/s"
            if covered:
                msg += f"  {covered * 100:5.1f}%"
            sys.stdout.write(msg)
            sys.stdout.flush()
            last_report = now

    elapsed = time.perf_counter() - t0
    sys.stdout.write("\r" + " " * 72 + "\r")

    if not rows:
        raise SystemExit("decoded zero frames -- is the file readable?")

    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    # Re-ingesting must not silently drop tags recorded the first time round.
    if existing:
        tags = sorted(set(tags) | set(existing.get("tags", [])))
    store.write_manifest(fp, profile.name, {
        "sample_hz": args.hz,
        "n_samples": len(rows),
        "minimap_mode": minimap.as_dict(),
        "tags": tags,
    })
    path = store.write_primitives(rows, fp, profile.name, date)

    span_ms = rows[-1]["t_ms"] - rows[0]["t_ms"]
    print(f"L1 wrote   {len(rows)} rows covering {_fmt_hms(span_ms)}")
    print(f"           {path}")
    print(f"           {path.stat().st_size / 1e6:.2f} MB  "
          f"({path.stat().st_size / max(1, len(rows)):.0f} B/sample)")
    print(f"took       {elapsed:.1f}s  ({len(rows) / elapsed:.1f} samples/s)")

    cfg = SegmentConfig()
    spans = segment({k: np.array([r[k] for r in rows]) for k in rows[0]}, cfg)
    store.write_spans(spans, fp.session_id, date, cfg)
    print(f"L2 wrote   {len(spans)} spans  (segmenter {SEGMENTER_VERSION})")
    print(f"\nnext: reticle inspect {fp.session_id}")
    return 0


# --------------------------------------------------------------------------- segment

def cmd_segment(args) -> int:
    store = Store(args.store)
    cfg = SegmentConfig(
        minimap_dchange_min=args.minimap_dchange,
        hud_edge_min=args.hud_edge,
        active_motion_min=args.active_motion,
        smooth_window=args.smooth,
        min_span_ms=args.min_span * 1000.0,
    )

    targets = store.sessions() if args.all else [_resolve_session(store, args.session)]
    if not targets:
        raise SystemExit(f"store is empty: {store.root}")

    print(f"config     {cfg.as_dict()}")
    for manifest in targets:
        sid = manifest["session_id"]
        date = _date_of(manifest)
        table = store.read_primitives(sid, date)
        t0 = time.perf_counter()
        spans = segment(table, cfg)
        store.write_spans(spans, sid, date, cfg)
        dt = time.perf_counter() - t0

        total = sum(s["duration_ms"] for s in spans) or 1.0
        by_state = {st: 0.0 for st in STATES}
        for s in spans:
            by_state[s["state"]] += s["duration_ms"]
        share = "  ".join(f"{st} {by_state[st] / total * 100:4.1f}%" for st in STATES)
        print(f"  {sid}  {len(spans):>4d} spans  {share}   ({dt * 1000:.0f} ms, no video touched)")

        if args.show_signals:
            _show_signals(table, cfg)
    return 0


def _show_signals(table: dict[str, np.ndarray], cfg: SegmentConfig) -> None:
    """Percentiles of the columns the classifier thresholds on, for calibration."""
    print("\n  signal percentiles (pick thresholds between the modes)")
    print(f"    {'column':<22}{'p05':>9}{'p25':>9}{'p50':>9}{'p75':>9}{'p95':>9}")
    watched = ["motion", "edge_density", "minimap_dchange"] + [
        f"{roi}_edge" for roi in HUD_CHROME_ROIS
    ]
    for col in watched:
        if col not in table:
            continue
        v = np.asarray(table[col], dtype=np.float64)
        qs = np.percentile(v, [5, 25, 50, 75, 95])
        print(f"    {col:<22}" + "".join(f"{q:9.4f}" for q in qs))
    print(f"\n    thresholds in use: minimap_dchange>={cfg.minimap_dchange_min:g}  "
          f"hud_edge>={cfg.hud_edge_min:g}  motion>={cfg.active_motion_min:g}\n")


# --------------------------------------------------------------------------- inspect

def cmd_inspect(args) -> int:
    store = Store(args.store)
    sessions = store.sessions()
    if not sessions:
        raise SystemExit(f"store is empty: {store.root}\nrun `reticle ingest <video>` first")

    if args.session is None and len(sessions) > 1:
        print(f"store      {store.root}")
        print(f"{'session':<14}{'source':<38}{'samples':>9}  ingested")
        for m in sessions:
            print(f"{m['session_id']:<14}{m['source']['filename'][:36]:<38}"
                  f"{m.get('n_samples', 0):>9}  {m['ingested_at'][:19]}")
        print("\nname a session for detail: reticle inspect <session_id>")
        return 0

    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    date = _date_of(manifest)
    src = manifest["source"]
    table = store.read_primitives(sid, date)
    spans_tbl = store.read_spans(sid, date)

    n = len(table["t_ms"])
    covered = float(table["t_ms"][-1] - table["t_ms"][0]) if n else 0.0

    print(f"session    {sid}")
    print(f"source     {src['filename']}")
    print(f"           {src['width']}x{src['height']} @ {src['fps']:.2f}fps  "
          f"{_fmt_hms(src['duration_ms'])}  {src['size_bytes'] / 1e9:.2f} GB")
    print(f"           {src['path']}")
    print(f"profile    {manifest['source_profile']}")
    print(f"ingested   {manifest['ingested_at'][:19]}Z at {manifest.get('sample_hz', '?')} Hz")

    if spans_tbl is None:
        print("\nno spans yet -- run `reticle segment`")
        return 0

    spans = spans_tbl.to_pylist()
    total = sum(s["duration_ms"] for s in spans) or 1.0
    by_state: dict[str, list] = {st: [] for st in STATES}
    for s in spans:
        by_state[s["state"]].append(s)

    print(f"\nspans      {len(spans)}  (segmenter {spans[0]['segmenter_version']})")
    print(f"  {'state':<10}{'count':>7}{'duration':>12}{'share':>9}{'longest':>10}")
    for st in STATES:
        group = by_state[st]
        dur = sum(s["duration_ms"] for s in group)
        longest = max((s["duration_ms"] for s in group), default=0.0)
        print(f"  {st:<10}{len(group):>7}{_fmt_hms(dur):>12}{dur / total * 100:8.1f}%{_fmt_ms(longest):>10}")

    in_match = sum(s["duration_ms"] for s in spans if s["state"] in ("idle", "active"))
    active = sum(s["duration_ms"] for s in spans if s["state"] == "active")

    # The design doc's stage-01 funnel, instantiated with this capture's numbers.
    raw_frames = int(src["frame_count"]) if src["frame_count"] else 0
    print(f"\nfunnel     (design doc SS3)")
    if raw_frames:
        print(f"  raw frames        {raw_frames:>10,}")
    print(f"  sampled           {n:>10,}   {n / raw_frames * 100:5.2f}% of raw" if raw_frames
          else f"  sampled           {n:>10,}")
    in_match_samples = int(n * in_match / total) if total else 0
    print(f"  in-match samples  {in_match_samples:>10,}   {in_match / total * 100:5.2f}% of capture")
    print(f"  active samples    {int(n * active / total):>10,}   {active / total * 100:5.2f}% of capture")

    if args.spans:
        print(f"\n  {'#':>4}  {'state':<8}{'start':>9}{'end':>9}{'dur':>9}{'motion':>9}")
        for s in spans[: args.spans]:
            print(f"  {s['span_idx']:>4}  {s['state']:<8}{_fmt_ms(s['t_start_ms']):>9}"
                  f"{_fmt_ms(s['t_end_ms']):>9}{_fmt_ms(s['duration_ms']):>9}{s['mean_motion']:9.4f}")
        if len(spans) > args.spans:
            print(f"  ... {len(spans) - args.spans} more")
    return 0


# --------------------------------------------------------------------------- frames

def cmd_frames(args) -> int:
    import cv2

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    src = manifest["source"]
    path = Path(src["path"])
    if not path.is_file():
        raise SystemExit(f"source no longer at {path}\n(L0 is never copied into the store)")

    date = _date_of(manifest)
    table = store.read_primitives(manifest["session_id"], date)
    labels = classify(table, SegmentConfig())

    out_dir = Path(args.out) if args.out else Path.cwd() / f"frames_{manifest['session_id']}"
    out_dir.mkdir(parents=True, exist_ok=True)

    step_ms = args.every * 1000.0
    wanted = np.arange(float(table["t_ms"][0]), float(table["t_ms"][-1]), step_ms)
    cap = cv2.VideoCapture(str(path))
    written = 0
    try:
        for t_ms in wanted:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t_ms))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            i = int(np.argmin(np.abs(table["t_ms"] - t_ms)))
            state = STATES[int(labels[i])]
            out = out_dir / f"{int(t_ms):08d}ms_{state}.jpg"
            cv2.imwrite(str(out), frame)
            written += 1
    finally:
        cap.release()

    print(f"wrote {written} frames to {out_dir}")
    print("filenames carry the baseline label -- rename any that are wrong;")
    print("that correction set is what a trained stage-01 classifier gets fitted on.")
    return 0


# --------------------------------------------------------------------------- hud

class _FP:
    """Minimal fingerprint stand-in -- write_hud only needs these two fields."""

    def __init__(self, src: dict, session_id: str):
        self.session_id = session_id
        self.content_key = src["content_key"]


class _MinimapPass:
    """Stage 02 minimap position, as a fed object. See `_HudPass` for why."""

    def __init__(self, store, manifest, profile, spans, args):
        import cv2

        self.src = manifest["source"]
        self.w, self.h = int(self.src["width"]), int(self.src["height"])
        self.box = minimap_roi_px(profile, self.w, self.h)
        sid = manifest["session_id"]
        med = geometry.reference_static(sid, store.root)
        sd = geometry.stability(sid, store.root, med.shape[:2])
        self.floor = floor_mask(med, sd=sd)
        self.slab = slab_mask(med, sd=sd)
        # The reference the widget test correlates against. See `widget_drawn`.
        self.sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)
        # Declared for `passes.Reader`.
        self.name = "minimap"
        self.hz = args.minimap_hz
        self.spans = spans         # the minimap has nothing to say off-round
        self.step_ms = 1000.0 / args.minimap_hz
        # The last position READ and when, which is not the last frame fed:
        # a widget-absent frame, a dropped frame and a stall all leave the
        # previous point older than one nominal period. `pick_self`'s gate is
        # how far the player could have moved since, so it needs the real
        # elapsed time and not the rate this reader was configured with.
        self.prev = None
        self.prev_t = None
        self.rows: list[dict] = []
        self.n_absent = 0
        print(f"floor      {self.floor.mean() * 100:.1f}% of the widget is walkable")

    def feed(self, smp) -> None:
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        # **Is the widget even there.** Two things remove it -- the death screen
        # and the M key -- and in both the ROI holds ordinary world pixels that
        # a colour-keyed icon reader can accept. This reader previously had no
        # such guard
        # at all: measured over 27757 frames of a06f04a0059f at 15 Hz, 1394
        # (5.0%) were widget-absent and yielded 3605 self and 4178 ally
        # candidates, 2.6 per frame, every one of them a phantom.
        #
        # A refused frame is recorded as a row with NULL positions rather than
        # dropped, so the track keeps its time axis and `filter_track`'s gap
        # interpolation sees the hole for what it is. Dropping the row would
        # make the absence invisible, which is the failure `reticle.census`
        # exists to catch -- and it would silently shorten every rate this
        # stage reports.
        if not widget_drawn(crop, self.sgray, self.floor):
            self.n_absent += 1
            self.rows.append({
                "frame_idx": smp.frame_idx, "t_ms": smp.t_ms,
                "self_x": None, "self_y": None, "n_allies": 0,
                "ally_x": [None] * MAX_ALLIES, "ally_y": [None] * MAX_ALLIES,
                # The column that separates NOBODY WAS LOOKING from THE READER
                # REFUSED. Both wrote the same NULL until minimap-0.6.0, so no
                # stored row could say which, and `belief.resolve` had to treat
                # them alike -- only the second is a detection failure, and
                # only the first forbids a belief outright.
                "widget_drawn": False,
            })
            return
        dt_ms = (self.step_ms if self.prev_t is None
                 else smp.t_ms - self.prev_t)
        # Fit one icon around all keyed fragments. A connected-component
        # centroid sits near the middle of one broken arc, roughly one radius
        # away from the icon centre. `self_icons` instead fits the shared ring
        # and collapses nearby fragments. Position does not require a readable
        # facing: bearing may be unknown while the centre is supported. There
        # is deliberately no blob fallback; switching estimators introduces a
        # radius-sized, rate-dependent bias.
        fitted = self_icons(crop, self.floor, require_facing=False,
                            support=self.slab)
        pick = pick_self(fitted, self.prev, dt_ms, widget_scale(crop.shape[1]))
        if pick is not None:
            self.prev, self.prev_t = pick, smp.t_ms
        allies = sorted(ally_rings(crop, self.floor), key=lambda c: -c[0])[:MAX_ALLIES]
        ally_x = [c[1] for c in allies] + [None] * (MAX_ALLIES - len(allies))
        ally_y = [c[2] for c in allies] + [None] * (MAX_ALLIES - len(allies))
        self.rows.append({
            "frame_idx": smp.frame_idx,
            "t_ms": smp.t_ms,
            "self_x": pick[0] if pick else None,
            "self_y": pick[1] if pick else None,
            "n_allies": len(allies),
            "ally_x": ally_x,
            "ally_y": ally_y,
            "widget_drawn": True,
        })


def _active_spans(store, sid, date):
    """The active spans, or a clear failure -- both stages need them."""
    tbl = store.read_spans(sid, date)
    if tbl is None:
        raise SystemExit(f"no spans for session {sid} -- run `reticle segment {sid}` first")
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]
    if not spans:
        raise SystemExit(f"session {sid} has no active spans -- nothing to track")
    return spans


def cmd_hud(args) -> int:
    """Stage 02: decode the capture again and read the scoreline off each frame.

    This stage needs pixels, so unlike `segment` it cannot recompute from stored
    L1 -- it re-opens the source the manifest points at.
    """
    import cv2

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    date = _date_of(manifest)
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])

    if store.has_hud(sid, date) and not args.force:
        print(f"cache hit  session {sid} already has HUD reads at {HUD_VERSION}")
        print(f"           {store.hud_path(sid, date)}")
        print("           pass --force to re-read")
        return 0

    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(
            f"source media has moved: {media}\n"
            "the manifest records where it was at ingest time"
        )

    print(f"session    {sid}  ({src['filename']})")
    print(f"profile    {profile.name}  ({HUD_VERSION})")
    print(f"sampling   {args.hz:g} Hz")

    hp = _HudPass(store, manifest, profile, args)
    rows = hp.rows
    t0 = time.perf_counter()
    last = t0
    for smp in sample_frames(str(media), args.hz, src["fps"], args.max_frames):
        hp.feed(smp)
        now = time.perf_counter()
        if now - last >= 2.0:
            pct = (smp.t_ms / src["duration_ms"] * 100) if src["duration_ms"] else 0.0
            sys.stdout.write(f"\r  {len(rows):>7d} frames  {_fmt_hms(smp.t_ms)}  {pct:5.1f}%")
            sys.stdout.flush()
            last = now
    sys.stdout.write("\r" + " " * 72 + "\r")

    if not rows:
        raise SystemExit("decoded zero frames -- is the file readable?")

    out = store.write_hud(rows, _FP(src, sid), profile.name, date)
    dt = time.perf_counter() - t0

    n = len(rows)
    got_clock = sum(1 for r in rows if r["clock_ms"] is not None)
    got_score = sum(1 for r in rows if r["score_left"] is not None and r["score_right"] is not None)
    got_hp = sum(1 for r in rows if r["hp"] is not None)
    got_ammo = sum(1 for r in rows if r["ammo_mag"] is not None)
    kf_frames = sum(1 for r in rows if r["kf_entries"] > 0)
    kf_kill = sum(1 for r in rows if r["kf_player_kill"])
    kf_death = sum(1 for r in rows if r["kf_player_death"])
    print(f"HUD wrote  {n} rows  ({dt:.1f}s, {n / max(dt, 1e-9):.1f} rows/s)")
    print(f"           {out}")
    print(f"           {out.stat().st_size / 1e3:.1f} kB")
    print(f"read rate  clock {got_clock}/{n} ({got_clock / n * 100:.1f}%)   "
          f"scores {got_score}/{n} ({got_score / n * 100:.1f}%)")
    print(f"           hp    {got_hp}/{n} ({got_hp / n * 100:.1f}%)   "
          f"ammo   {got_ammo}/{n} ({got_ammo / n * 100:.1f}%)")
    ev = player_events(
        [r["t_ms"] for r in rows],
        [r["kf_kill_mask"] for r in rows],
        [r["kf_death_mask"] for r in rows],
        [r["kf_kill_wx"] for r in rows],
        [r["kf_death_wx"] for r in rows],
    )
    print(f"killfeed   {kf_frames} frames show an entry   "
          f"player in-frame: {kf_kill} kill, {kf_death} death")
    print(f"           tracked entries: {ev['kills']} kills, {ev['deaths']} deaths")
    unattr = sum(1 for r in rows if r["kf_unattributed"])
    if unattr:
        print(f"           ! {unattr} frames hold an entry whose name an overlay covers "
              f"-- attribution impossible there")
    print(f"\nnext: reticle verify {sid}")
    return 0


# --------------------------------------------------------------------------- minimap

def cmd_minimap(args) -> int:
    """Stage 02: player position off the minimap.

    Needs `reticle segment` to have run first -- active spans bound both the
    static-map sample and the decode itself, since the minimap has nothing
    to say off-round. Sampled at a higher rate than `hud` (default 15 Hz vs
    2 Hz): everything downstream of position is a *speed* measurement, and
    2 Hz cannot support one. See `reticle/minimap.py` for what is and is not
    validated yet -- self is a real track, allies are per-frame candidates.
    """
    import cv2

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    date = _date_of(manifest)
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])

    if store.has_minimap(sid, date) and not args.force:
        print(f"cache hit  session {sid} already has minimap positions at {MINIMAP_VERSION}")
        print(f"           {store.minimap_path(sid, date)}")
        print("           pass --force to re-read")
        return 0

    spans = _active_spans(store, sid, date)

    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(
            f"source media has moved: {media}\n"
            "the manifest records where it was at ingest time"
        )
    fps = float(src["fps"])
    print(f"session    {sid}  ({src['filename']})")
    print(f"profile    {profile.name}  ({MINIMAP_VERSION})")
    print(f"roi        active spans {len(spans)} "
          f"({sum(b - a for a, b in spans) / 1000.0:.0f}s)")
    print(f"sampling   {args.hz:g} Hz")

    args.minimap_hz = args.hz
    mp = _MinimapPass(store, manifest, profile, spans, args)
    rows, step_ms = mp.rows, mp.step_ms
    t0 = time.perf_counter()
    last = t0
    for smp in sample_spans(str(media), spans, args.hz, fps):
        mp.feed(smp)
        now = time.perf_counter()
        if now - last >= 2.0:
            pct = (smp.t_ms / src["duration_ms"] * 100) if src["duration_ms"] else 0.0
            sys.stdout.write(f"\r  {len(rows):>7d} frames  {_fmt_hms(smp.t_ms)}  {pct:5.1f}%")
            sys.stdout.flush()
            last = now
    sys.stdout.write("\r" + " " * 72 + "\r")

    if not rows:
        raise SystemExit("decoded zero frames inside active spans -- is segmentation right?")

    out = store.write_minimap(rows, _FP(src, sid), profile.name, date)
    dt = time.perf_counter() - t0

    n = len(rows)
    got_self = sum(1 for r in rows if r["self_x"] is not None)
    got_ally = sum(1 for r in rows if r["n_allies"] > 0)
    print(f"minimap wrote  {n} rows  ({dt:.1f}s, {n / max(dt, 1e-9):.1f} rows/s)")
    print(f"               {out}")
    print(f"               {out.stat().st_size / 1e3:.1f} kB")
    print(f"widget     absent {mp.n_absent}/{n} ({mp.n_absent / n * 100:.1f}%) "
          f"-- death screen or the full-size map; those rows carry no position")
    print(f"self       raw {got_self}/{n} ({got_self / n * 100:.1f}%)")

    # NULL rows go IN, not out: they are how `filter_track` tells a widget-absent
    # hole from a detection miss, and stripping them here is what made the
    # comment in `_MinimapPass.feed` describe behaviour nothing implemented.
    track = filter_track([(r["t_ms"], r["self_x"], r["self_y"]) for r in rows],
                         step_ms,
                         widget_scale(minimap_roi_px(profile, w, h)[2]
                                      - minimap_roi_px(profile, w, h)[0]))
    print(f"           filtered {len(track)} points "
          f"({len(track) / n * 100:.1f}% coverage after gap interpolation)")
    sp = np.array([np.hypot(b[1] - a[1], b[2] - a[2]) / ((b[0] - a[0]) / 1000.0)
                   for a, b in zip(track, track[1:]) if 0 < b[0] - a[0] <= 1.5 * step_ms])
    if sp.size:
        print(f"           px/s median {np.median(sp):.1f}  p95 {np.percentile(sp, 95):.1f}  "
              f"jumps>60px/s: {(sp > 60).mean() * 100:.1f}%")
    print(f"ally       at least one candidate: {got_ally}/{n} ({got_ally / n * 100:.1f}%)")
    return 0


def cmd_scan(args) -> int:
    """Stages 02 HUD and 02 minimap in ONE decode of the capture.

    Not a new stage and not a new number: it drives the same `_HudPass` and
    `_MinimapPass` the two commands drive, over `decode.sample_multi`, and
    writes the same two L1 tables. Frame-for-frame identical to running both --
    verified by comparing the sampled timestamp lists, which match exactly.

    **Why it is worth a command.** Decoding is 93% of the cost of a stage (13.17
    s against 0.94 s of analysis over 300 frames), and raising the sample rate
    is nearly free because `grab()` decodes every frame anyway -- 15 Hz costs
    31% more than 2 Hz, not seven times. So two stages that each open the file
    cost two passes, and fused they cost about 1.3. Measured over 200 s of
    c40d950031bb: 46.77 s as two passes, 25.93 s as one, a **45% saving**.

    Needs `segment` to have run, because the minimap half is bounded by active
    spans -- which is also why this cannot be the path for a session's FIRST
    read: spans are computed from the HUD table this would be writing. It is
    the path for every re-read after that, which is the expensive case (a
    HUD_VERSION bump re-reads every session in the store) and the common one.
    """
    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    date = _date_of(manifest)
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])

    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(
            f"source media has moved: {media}\n"
            "the manifest records where it was at ingest time"
        )
    channels = set(args.only or ('hud', 'minimap', 'ping', 'roster', 'scoreboard',
                                 'ally_icon'))
    # IDENTITY RIDES EVERY SCAN. The top bar is drawn on every frame, so naming
    # the ten agents costs no decode of its own -- it joins the pass at 0.1 Hz.
    # A scan narrowed with `--only` is testing one specific thing and is left
    # alone; anything else reads the lineup unless `--no-lineup` says not to.
    want_lineup = args.lineup and not args.only
    spans = (_active_spans(store, sid, date)
             if channels & {'minimap', 'ping', 'ally_icon'} else [])
    fps = float(src["fps"])

    want_hud = 'hud' in channels and (args.force or not store.has_hud(sid, date))
    want_portraits = ('hud' in channels and
                      (args.force or store.events_version(
                          "killfeed_portrait", sid) != KILLFEED_PORTRAIT_VERSION))
    want_mm = 'minimap' in channels and (args.force or not store.has_minimap(sid, date))
    # Pings are events rather than a versioned table, but the cache key is the
    # VERSION, not the file's existence. Keying on existence made `PING_VERSION`
    # a stamp nothing read: bumping it re-read nothing, and a store could hold
    # pings at three definitions with no way to say which sessions were stale --
    # which is the one job version.py says a stamp exists to do.
    want_ping = 'ping' in channels and args.ping and (args.force
                               or store.events_version("ping", sid) != PING_VERSION)
    want_roster = 'roster' in channels and args.roster and (args.force or not store.has_roster(sid, date))
    # Rides the minimap's active spans at 2 Hz; versioned by its own stamp, so a
    # descriptor change re-reads descriptors and leaves positions alone.
    want_ally = 'ally_icon' in channels and (
        args.force or store.events_version("ally_icon", sid) != ALLY_ICON_VERSION)
    want_scoreboard = ('scoreboard' in channels and args.scoreboard and
                       (args.force or store.events_version("scoreboard", sid)
                        != SCOREBOARD_VERSION))
    if not (want_hud or want_portraits or want_mm or want_ping or want_roster
            or want_scoreboard or want_ally):
        print(f"cache hit  session {sid}: requested channels are current or disabled; "
              "--force to re-read")
        return 0

    print(f"session    {sid}  ({src['filename']})")
    print(f"profile    {profile.name}")
    print(f"stages     " + ", ".join(
        ([f"hud {args.hz:g} Hz, whole capture"] if want_hud else [])
        + ([f"killfeed portraits {args.hz:g} Hz, whole capture"]
           if want_portraits else [])
        + ([f"minimap {args.minimap_hz:g} Hz, {len(spans)} active spans "
            f"({sum(b - a for a, b in spans) / 1000.0:.0f}s)"] if want_mm else [])
        + ([f"ping {args.ping_hz:g} Hz, active spans"] if want_ping else [])
        + ([f"roster {args.hz:g} Hz, whole capture"] if want_roster else [])
        + ([f"scoreboard {args.hz:g} Hz, whole capture"] if want_scoreboard else [])
        + ([f"ally icons {args.ally_hz:g} Hz, active spans"] if want_ally else [])))

    hp = _HudPass(store, manifest, profile, args) if want_hud else None
    mp = _MinimapPass(store, manifest, profile, spans, args) if want_mm else None

    ctx = SessionContext(store=store, manifest=manifest, profile=profile, spans=spans)
    kp = (KillfeedPortraitReader(
              profile, ctx.wh, mask=ctx.kf_mask(), hz=args.hz, spans=None)
          if want_portraits else None)
    # Pings ride whatever pass is already happening -- they never justify a
    # decode of their own, which is why this is on by default and why it takes
    # the floor mask the minimap half has already paid for rather than
    # deriving a second one. It cannot move the HUD or minimap numbers:
    # `sample_multi` advances each reader's phase only when that reader is in
    # `want`, so a third reader adds retrieved frames and changes nobody
    # else's. That is an argument; the check is in `reticle metrics`.
    pp = None
    if want_ping:
        pp = PingReader(
            floor=mp.floor if mp is not None else ctx.floor(),
            box=minimap_roi_px(profile, *ctx.wh),
            sgray=mp.sgray if mp is not None else ctx.sgray(),
            hz=args.ping_hz,
            spans=spans,
        )

    # The roster rides the HUD's frames: same ROIs, same rate, same whole-capture
    # span, so `sample_multi` serves one retrieval to both and this costs a
    # Laplacian per frame and no decode at all. That is the point of the
    # registry -- a reader that cannot justify opening the file joins a pass
    # that was happening anyway.
    rp = (RosterReader(profile, ctx.wh, hz=args.hz, spans=None)
          if want_roster else None)
    sp = (ScoreboardReader(profile.name, hz=args.hz, spans=None,
                           min_confidence=args.min_confidence,
                           min_margin=args.min_margin, icons_root=store.root)
          if want_scoreboard else None)

    lp = (LineupReader(profile, ctx.wh, store.root, name=f"lineup:{sid}")
          if want_lineup else None)
    ap = None
    if want_ally:
        med = ctx.map_reference()
        ap = AllyIconReader(
            floor=mp.floor if mp is not None else ctx.floor(),
            slab=mp.slab if mp is not None else slab_mask(
                med, sd=geometry.stability(sid, store.root, med.shape[:2])),
            static=med, box=minimap_roi_px(profile, *ctx.wh), hz=args.ally_hz,
            spans=spans)
    readers = [r for r in (hp, kp, mp, pp, rp, sp, lp, ap) if r is not None]

    t0 = time.perf_counter()
    last = [t0]

    def progress(n, smp):
        now = time.perf_counter()
        if now - last[0] >= 2.0:
            pct = (smp.t_ms / src["duration_ms"] * 100) if src["duration_ms"] else 0.0
            sys.stdout.write(f"\r{n:>7d} frames  {_fmt_hms(smp.t_ms)}  {pct:5.1f}%")
            sys.stdout.flush()
            last[0] = now

    n_dec = passes_run(ctx, readers, progress)
    sys.stdout.write("\r" + " " * 72 + "\r")
    dt = time.perf_counter() - t0

    if hp is not None:
        if not hp.rows:
            raise SystemExit("decoded zero frames -- is the file readable?")
        out = store.write_hud(hp.rows, _FP(src, sid), profile.name, date)
        ev = player_events(
            [r["t_ms"] for r in hp.rows],
            [r["kf_kill_mask"] for r in hp.rows],
            [r["kf_death_mask"] for r in hp.rows],
            [r["kf_kill_wx"] for r in hp.rows],
            [r["kf_death_wx"] for r in hp.rows],
        )
        print(f"HUD        {len(hp.rows)} rows -> {out}")
        print(f"           tracked entries: {ev['kills']} kills, {ev['deaths']} deaths")
    if kp is not None:
        events = kp.events(sid)
        out = store.write_events("killfeed_portrait", sid, events)
        print(f"portraits  {len(events) - 1} observations -> {out}")
    if mp is not None:
        if not mp.rows:
            raise SystemExit("decoded zero frames inside active spans "
                             "-- is segmentation right?")
        out = store.write_minimap(mp.rows, _FP(src, sid), profile.name, date)
        got = sum(1 for r in mp.rows if r["self_x"] is not None)
        print(f"minimap    {len(mp.rows)} rows -> {out}")
        print(f"           widget absent {mp.n_absent}/{len(mp.rows)} "
              f"({mp.n_absent / len(mp.rows) * 100:.1f}%)")
        print(f"           self raw {got}/{len(mp.rows)} "
              f"({got / len(mp.rows) * 100:.1f}%)")
    if ap is not None:
        from .adjudication.minimap_candidates import (
            MINIMAP_ICON_DECISION_VERSION, accepted, ally_decisions)
        candidate_revision = store.write_candidates("ally_icon", sid,
                                                     ap.candidate_rows(sid), ap.frames)
        batch = store.read_candidate_batch("ally_icon", sid, candidate_revision)
        candidates = batch["rows"]
        store.write_decisions("ally_icon", sid, candidate_revision,
                              MINIMAP_ICON_DECISION_VERSION,
                              ally_decisions(candidates))
        decisions = store.read_decisions("ally_icon", sid, candidate_revision,
                                         MINIMAP_ICON_DECISION_VERSION)
        kept = accepted(candidates, decisions)
        # Check the previous output contract before publishing the replay.
        ap.events(sid, kept, candidate_revision)
        events = AllyIconReader.replay_events(sid, batch["frames"], kept, ap.hz,
                                               candidate_revision)
        out = store.write_events("ally_icon", sid, events)
        cov = events[0]
        print(f"ally icons {cov['frames']} frames, {cov['icons']} icons, "
              f"{cov['described']} described -> {out}")
        print(f"           refused {cov['refused_reasons']}")
    if lp is not None:
        import json
        result = lp.finish()[0]
        out = store.root / "lineups" / f"{sid}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({**result, "session": sid}, indent=2),
                       encoding="utf-8")
        named = {side: [r["agent"] for r in rows if r["agent"]]
                 for side, rows in result["sides"].items()}
        print(f"lineup     {result['frames']} frames -> {out}")
        for side in ("ally", "enemy"):
            got = named[side]
            print(f"           {side} {len(got)}/5 named"
                  + (f": {', '.join(got)}" if got else
                     " -- no slot separated from its runner-up"))
    if rp is not None:
        if not rp.rows:
            raise SystemExit("decoded zero frames -- is the file readable?")
        out = store.write_roster(rp.rows, _FP(src, sid), profile.name, date)
        n = len(rp.rows)
        both = sum(1 for r in rp.rows
                   if r["alive_ally"] is not None and r["alive_enemy"] is not None)
        five = sum(1 for r in rp.rows if r["alive_ally"] == 5 and r["alive_enemy"] == 5)
        over = sum(1 for r in rp.rows
                   if (r["alive_ally"] or 0) > 5 or (r["alive_enemy"] or 0) > 5)
        # An empty bar is DRAWN AND EMPTY (the team is wiped) or NOT DRAWN, and
        # per-slot detail cannot separate them -- so this reader refuses, and
        # `roster.resolve()` answers it later from the scoreline, which is not
        # available in a roster-only pass. What is printed is therefore the size
        # of the population this table defers rather than a defect rate, and
        # `(0,0)` no longer occurs here at all (roster-split-0.2.0).
        zero = sum(1 for r in rp.rows
                   if r["alive_ally"] == 0 and r["alive_enemy"] == 0)
        defer = sum(1 for r in rp.rows
                    if r["alive_ally"] is None or r["alive_enemy"] is None)
        if defer:
            print(f"           {defer} rows defer to the HUD gate "
                  f"({defer / n * 100:.1f}%) -- `reticle audit` resolves them")
        print(f"roster     {n} rows -> {out}")
        print(f"           answered {both}/{n} ({both / n * 100:.1f}%), "
              f"5v5 on {five} ({five / n * 100:.1f}%)")
        if zero:
            print(f"           {zero} rows read 0/0 ({zero / n * 100:.1f}%) "
                  f"-- ambiguous roster absence/zero counts; see roster.py")
        # `over` is a HARD invariant -- a team cannot field six -- so it is
        # printed even when zero. A count above five is not a bad reading to
        # weigh, it is proof the split rule is wrong, and a reader that only
        # reports what it accepted cannot be audited.
        if over:
            print(f"           !! {over} rows report MORE THAN FIVE alive "
                  f"-- the split rule is wrong, do not use this table")

    if pp is not None:
        pp.finish()
        out = store.write_events("ping", sid, pp.events(sid))
        by: dict[str, int] = {}
        for kind, *_r in pp.hits:
            by[kind] = by.get(kind, 0) + 1
        print(f"ping       {len(pp.hits)} confirmed -> {out}")
        print(f"           " + (", ".join(f"{k} x{v}" for k, v in sorted(by.items()))
                                or "none"))
        # Both refusal counts are printed on purpose. A detector that reports
        # only what it accepted cannot be audited, and `unconfirmed` in
        # particular is a population -- runs cut off by a span end, the death
        # screen or the M key -- whose size says how much of the session this
        # reader could not measure at all.
        print(f"           {len(pp.unconfirmed)} unconfirmed (observation "
              f"stopped), {len(pp.rejected)} refused on lifetime, "
              f"{pp.n_absent} frames widget-absent")
    if sp is not None:
        out = store.write_events("scoreboard", sid, sp.events(sid))
        accepted = sum(r["credits"] is not None for r in sp.rows)
        candidates = sum(r["credits_candidate"] is not None for r in sp.rows)
        print(f"scoreboard {sp.frames_open}/{sp.frames_offered} frames open, "
              f"{accepted}/{candidates} credit candidates gated -> {out}")
    print(f"one pass   {n_dec} frames retrieved in {dt:.1f}s")
    print(f"\nnext: reticle verify {sid}")
    return 0


# --------------------------------------------------------------------------- glyphs

def cmd_glyphs(args) -> int:
    """Mine glyph clusters from a capture so they can be labelled into templates.

    Templates are bootstrapped from real footage rather than a font file,
    because what matters is how this build renders at this resolution. Run this,
    open the montage, then re-run with --label giving one character per cluster.
    """
    import cv2

    profile = get_profile(args.profile)
    roi = scoreline_roi(profile)

    # Mine across every capture given. One session does not necessarily render
    # every digit at every size -- a score-sized "8" that never appears in the
    # sampled footage leaves a hole the matcher fills with the nearest wrong
    # digit, confidently. More captures, better coverage.
    glyphs = []
    frames = 0
    step = max(1, int(args.every * 1000))
    for video in args.video:
        fp = fingerprint(video)
        cap = cv2.VideoCapture(fp.path)
        before = len(glyphs)
        try:
            for ms in range(args.skip * 1000, int(fp.duration_ms or 0), step):
                cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frames += 1
                glyphs.extend(segment_glyphs(crop_gray(frame, roi, fp.width, fp.height)))
        finally:
            cap.release()
        print(f"  {fp.filename:<32} {len(glyphs) - before} glyphs")

    print(f"sampled    {frames} frames -> {len(glyphs)} glyphs")
    clusters = [(c, k) for c, k in cluster_glyphs(glyphs, args.tol) if k >= args.min_count]
    print(f"clusters   {len(clusters)} with count >= {args.min_count}")
    if not clusters:
        raise SystemExit("no glyph clusters found -- is the scoreline ROI right? run `reticle probe`")

    if args.label:
        labels = list(args.label)
        if len(labels) != len(clusters):
            raise SystemExit(
                f"--label has {len(labels)} characters but there are {len(clusters)} clusters"
            )
        out = Templates(labels, np.array([c for c, _ in clusters], dtype=np.float32))
        path = out.save(profile.name)
        counts: dict[str, int] = {}
        for ch in labels:
            counts[ch] = counts.get(ch, 0) + 1
        print(f"wrote      {path}  ({len(out)} templates)")
        print(f"per digit  {dict(sorted(counts.items()))}")
        return 0

    cell = 6
    cols = min(8, max(1, len(clusters)))
    rows_n = (len(clusters) + cols - 1) // cols
    tw, th = GLYPH_W * cell, GLYPH_H * cell
    sheet = np.full((rows_n * (th + 34) + 8, cols * (tw + 8) + 8, 3), 30, np.uint8)
    for i, (c, k) in enumerate(clusters):
        r, col = divmod(i, cols)
        img = cv2.resize((c * 255).astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST)
        y, x = r * (th + 34) + 8, col * (tw + 8) + 8
        sheet[y:y + th, x:x + tw] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        cv2.putText(sheet, f"#{i} n={k}", (x, y + th + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)
    dest = Path(args.out) if args.out else Path.cwd() / "glyphs.png"
    cv2.imwrite(str(dest), sheet)
    print(f"montage    {dest}")
    print("\nopen it, read the clusters left-to-right, then re-run with:")
    print(f'  reticle glyphs <videos> --label "<{len(clusters)} characters>"')
    return 0


# --------------------------------------------------------------------------- verify

def cmd_verify(args) -> int:
    """Check stored HUD reads against domain invariants (design doc SS3, stage 05).

    Reads stored L1 -- it never touches video. The invariants themselves live in
    checks.py so this and the dashboard agree on what counts as a fault.
    """
    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    r = check_hud(store.read_hud(sid, _date_of(manifest)))
    n = max(1, r["rows"])

    print(f"session    {sid}  ({manifest['source']['filename']})")
    print(f"rows       {r['rows']}  spanning {_fmt_hms(r['t_end_ms'] - r['t_start_ms'])}")
    print(f"read rate  clock {r['read_clock']}/{r['rows']} ({r['read_clock'] / n * 100:.1f}%)   "
          f"scores {r['read_scores']}/{r['rows']} ({r['read_scores'] / n * 100:.1f}%)")
    c = r["confidence"]
    if c:
        print(f"           glyph confidence  min {c['min']:.3f}  p05 {c['p05']:.3f}  "
              f"median {c['median']:.3f}")

    ck = r["clock"]
    steps = max(1, ck["steps"])
    print()
    print(f"clock      {ck['steps']} constrained steps")
    print(f"  in step  {ck['in_step']} track real time  ({ck['in_step'] / steps * 100:.2f}%)")
    print(f"  resets   {ck['resets']}  (jump lands on a known phase start, or a score moved)")
    print(f"  drift    {ck['drift']} unexplained jumps")
    for w in ck["worst"]:
        print(f"           {_fmt_hms(w['t_ms'])}  {w['from_ms'] / 1000:.0f}s -> "
              f"{w['to_ms'] / 1000:.0f}s  (off by {w['err_ms'] / 1000:.1f}s)")

    print()
    for name, key in (("score_L", "score_left_drops"), ("score_R", "score_right_drops")):
        d = r[key]
        print(f"{name:<10} {len(d)} decreases" + ("" if d else "  (monotonic)"))
        for x in d[:5]:
            print(f"           {_fmt_hms(x['t_ms'])}  {x['from']} -> {x['to']}")

    sj = r.get("sum_jumps") or []
    print(f'{"score_sum":<10} {len(sj)} illegal steps' + ("" if sj else "  (advances one round at a time)"))
    for x in sj[:5]:
        print(f"           {_fmt_hms(x['t_ms'])}  {x['from']} -> {x['to']} in {x['gap_ms'] / 1000:.1f}s")

    kf = r.get("killfeed")
    if kf:
        print()
        print(f"killfeed   {kf['kills']} kills, {kf['deaths']} deaths  (tracked entries)")
        known = kf.get("known")
        if known:
            k_err, d_err = kf["kills"] - known[0], kf["deaths"] - known[1]
            print(f"           scoreboard says {known[0]} / {known[1]}"
                  f"   delta {k_err:+d} / {d_err:+d}")
            allow = kf.get("allowed")
            if allow:
                print(f"           allowed {allow[0]:+d} / {allow[1]:+d}  "
                      f"(read correctly, not counted by the game "
                      f"-- see checks.KNOWN_DIVERGENCE)")
            re_ = kf.get("read_error")
            if re_:
                print(f"           READ ERROR {re_[0]:+d} / {re_[1]:+d}"
                      + ("   (this is the number that should go to zero)"
                         if any(re_) else "   -- exact"))
        else:
            print("           no scoreboard K/D recorded for this session "
                  "-- add it to checks.KNOWN_KD to score attribution")

    if r["final"]:
        f = r["final"]
        print()
        print(f"final      {f['left']} - {f['right']}  (sum {f['sum']} rounds)")
        if not r["reached_match_point"]:
            print("           ! neither side reached 13 -- capture may end before match point")

    print()
    if r["violations"] == 0:
        print("OK         no invariant violations")
    else:
        print(f"FAULTS     {r['violations']} violations -- see timestamps above")
    return 0


# --------------------------------------------------------------------------- board

def cmd_board(args) -> int:
    """Read every Tab scoreboard in the capture and score our count against it.

    This is the only check in the project that compares against the game's own
    running total rather than a domain invariant, and it is per-opening rather
    than per-match: the first opening where the two diverge contains the error.

    Needs pixels, so it re-decodes. Sampled coarsely on purpose -- the board
    stays up for seconds, so 2 Hz catches every opening without reading each one
    a dozen times.
    """
    import cv2

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(f"source media has moved: {media}")

    templates = Templates.load(profile.name)
    hud = store.read_hud(sid, _date_of(manifest))
    tracked = None
    if hud is not None:
        ht = hud.column("t_ms").to_pylist()
        kills = [e["t_first"] for e in track_entries(ht, hud.column("kf_kill_mask").to_pylist(),
                                                     _dividers(hud, "kf_kill_wx"))
                 if e["counted"]]
        deaths = [e["t_first"] for e in track_entries(ht, hud.column("kf_death_mask").to_pylist(),
                                                      _dividers(hud, "kf_death_wx"))
                  if e["counted"]]
        tracked = (kills, deaths)

    print(f"session    {sid}  ({src['filename']})")
    print(f"sampling   {args.hz:g} Hz for scoreboard openings")

    reads: list[tuple[float, object]] = []
    for smp in sample_frames(str(media), args.hz, src["fps"], args.max_frames):
        sb = read_scoreboard(smp.frame, templates,
                             args.min_confidence, args.min_margin)
        if sb.open_ and sb.player is not None and sb.player.complete:
            reads.append((smp.t_ms, sb))

    if not reads:
        raise SystemExit("no scoreboard found -- was it opened, and is the profile right?")

    # One row per opening: openings are runs of frames, so break on a gap.
    openings: list[list[tuple[float, object]]] = []
    for t, sb in reads:
        if openings and t - openings[-1][-1][0] <= args.gap * 1000:
            openings[-1].append((t, sb))
        else:
            openings.append([(t, sb)])

    print(f"openings   {len(openings)} ({len(reads)} frames read)\n")
    print("   at        board K/D/A   credits   ours K/D    delta     rows")
    worst = None
    for grp in openings:
        # the frame of this opening with the most rows fully read
        t, sb = max(grp, key=lambda p: sum(1 for r in p[1].rows if r.complete))
        pl = sb.player
        got = sum(1 for r in sb.rows if r.complete)
        cell = f"{pl.kills}/{pl.deaths}/{pl.assists}"
        if tracked is None:
            credit = f"{pl.credits:,}" if pl.credits is not None else "--"
            print(f"  {_fmt_hms(t):>8s}  {cell:>12s}  {credit:>8s}    "
                  f"{'-':>8s}    {'-':>6s}   {got}/10")
            continue
        ok = sum(1 for x in tracked[0] if x <= t)
        od = sum(1 for x in tracked[1] if x <= t)
        dk, dd = ok - pl.kills, od - pl.deaths
        flag = "" if (dk == 0 and dd == 0) else "  <-"
        if worst is None and (dk or dd):
            worst = t
        credit = f"{pl.credits:,}" if pl.credits is not None else "--"
        print(f"  {_fmt_hms(t):>8s}  {cell:>12s}  {credit:>8s}    {ok:2d} / {od:2d}   "
              f"{dk:+d} / {dd:+d}   {got}/10{flag}")

    last = max(openings[-1], key=lambda p: sum(1 for r in p[1].rows if r.complete))[1]
    print("\nfull board at the last opening:")
    for r in last.rows:
        who = "  <- you" if r.is_player else ""
        credit = str(r.credits) if r.credits is not None else f"-- ({r.credits_reason})"
        print(f"   {r.team:5s}  {str(r.kills):>3s} / {str(r.deaths):>3s} / "
              f"{str(r.assists):>3s}   {credit:>20s} creds{who}")
    if tracked is not None and worst is not None:
        print(f"\nfirst divergence at {_fmt_hms(worst)} -- the error is in or before that round")
    elif tracked is not None:
        print("\nno divergence at any opening")
    return 0


# --------------------------------------------------------------------------- kd

def cmd_kd(args) -> int:
    """Running kill/death totals per round, for checking against the scoreboard.

    Open the scoreboard in-game at a round boundary, read your K/D off it, and
    compare with the row for that round. A mismatch localises the error to a
    single round instead of a whole match, which is the entire point of doing it
    this way rather than comparing one number at the end.

    Rounds are inferred from the scoreline advancing, so a round the scoreline
    could not be read across is merged into its neighbour -- the `reads` column
    says how much of the round the scoreline was actually legible for.
    """
    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    table = store.read_hud(sid, _date_of(manifest))
    if table is None:
        raise SystemExit(f"no HUD reads for {sid} -- run: reticle hud {sid}")

    t = table.column("t_ms").to_pylist()
    sl = table.column("score_left").to_pylist()
    sr = table.column("score_right").to_pylist()
    kills = [a for a in track_entries(t, table.column("kf_kill_mask").to_pylist(),
                                      _dividers(table, "kf_kill_wx"))
             if a["counted"]]
    deaths = [a for a in track_entries(t, table.column("kf_death_mask").to_pylist(),
                                       _dividers(table, "kf_death_wx"))
              if a["counted"]]

    # round boundaries: the moment the two scores sum to one more than before
    bounds, prev, start = [], None, t[0] if t else 0.0
    for ts, a, b in zip(t, sl, sr):
        if a is None or b is None:
            continue
        total = a + b
        if prev is not None and total == prev + 1:
            bounds.append((start, ts, total, a, b))
            start = ts
        if prev is None or total != prev:
            prev = total
    if t:
        bounds.append((start, t[-1], (prev or 0) + 1, None, None))

    known = KNOWN_KD.get(sid)
    print(f"session    {sid}  ({manifest['source']['filename']})")
    print(f"rounds     {len(bounds)} inferred from the scoreline")
    if known:
        print(f"scoreboard {known[0]} / {known[1]} at the end of the match")
    print()
    print("  rd  ends at   score      K   D    cumulative   reads")
    ck = cd = 0
    for i, (r0, r1, _tot, a, b) in enumerate(bounds, start=1):
        k = sum(1 for e in kills if r0 <= e["t_first"] < r1)
        d = sum(1 for e in deaths if r0 <= e["t_first"] < r1)
        ck += k; cd += d
        n = sum(1 for ts in t if r0 <= ts < r1)
        got = sum(1 for ts, x in zip(t, sl) if r0 <= ts < r1 and x is not None)
        score = f"{a}-{b}" if a is not None else "  -  "
        print(f"  {i:2d}  {_fmt_hms(r1):>8s}  {score:>5s}   {k:2d}  {d:2d}"
              f"     {ck:2d} / {cd:2d}     {got * 100 // max(n, 1):3d}%")
    print()
    print(f"final      {ck} / {cd} tracked")
    if known:
        print(f"           {known[0]} / {known[1]} on the scoreboard"
              f"   delta {ck - known[0]:+d} / {cd - known[1]:+d}")
    print("\nopen the scoreboard each round and compare the cumulative column;")
    print("the first row where it diverges is the round holding the error.")
    return 0


# --------------------------------------------------------------------------- overlay

def _parse_ts(text: str | None) -> float | None:
    """Accept 90, 1:30 or 1:02:03 and return milliseconds."""
    if text is None:
        return None
    parts = text.split(":")
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise SystemExit(f"cannot read {text!r} as a timestamp (try 90, 1:30 or 1:02:03)")
    secs = 0.0
    for v in vals:
        secs = secs * 60 + v
    return secs * 1000.0


def cmd_overlay(args) -> int:
    """Render the extractors' decisions onto the capture, as a video.

    A debug aid, not part of the pipeline: it writes no L1 and reads no stored
    HUD. Every annotation comes from calling the real extractor on that frame,
    so the video cannot disagree with what `hud` would have recorded.
    """
    import cv2

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid = manifest["session_id"]
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(
            f"source media has moved: {media}\n"
            "the manifest records where it was at ingest time"
        )

    w, h = int(src["width"]), int(src["height"])
    fps = float(src["fps"] or 60.0)
    duration = float(src["duration_ms"] or 0.0)
    t_from = _parse_ts(args.start) or 0.0
    t_to = _parse_ts(args.end)
    if t_to is None:
        t_to = min(duration, t_from + args.seconds * 1000.0) if args.seconds else duration
    if t_to <= t_from:
        raise SystemExit(f"empty range: {_fmt_hms(t_from)} to {_fmt_hms(t_to)}")

    templates = Templates.load(profile.name)
    kf_roi = killfeed_roi(profile)

    print(f"session    {sid}  ({src['filename']})")
    print(f"range      {_fmt_hms(t_from)} .. {_fmt_hms(t_to)}  at {args.hz:g} Hz")

    # Calibrate the same overlay mask `hud` would use, over the whole capture
    # rather than the chosen range -- a mask measured from a few seconds would
    # call transient killfeed entries persistent.
    kf_mask = None
    if kf_roi is not None and not args.no_mask:
        cap = cv2.VideoCapture(str(media))
        cal = []
        try:
            step = max(1, int(duration / 40)) if duration else 1
            for ms in range(0, int(duration), step):
                cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                ok, fr = cap.read()
                if ok:
                    cal.append(fr)
        finally:
            cap.release()
        if cal:
            kf_mask = overlay_mask(cal, kf_roi, w, h)
            print(f"mask       {(~kf_mask).mean() * 100:.1f}% of the killfeed ROI "
                  f"from {len(cal)} frames")

    spans = None
    table = store.read_spans(sid, _date_of(manifest))
    if table is not None:
        spans = list(zip(table.column("t_start_ms").to_pylist(),
                         table.column("t_end_ms").to_pylist(),
                         table.column("state").to_pylist()))

    # Every minimap pixel reference comes from the baked (map, profile)
    # geometry. Session frames may determine ROI placement/dimensions only.
    mm_box = mm_floor = mm_passable = mm_sgray = mm_light = mm_slab = med = None
    if not args.no_minimap:
        geo = geometry.path_of(sid, args.store)
        if geo is None or not geo.is_file():
            print("minimap    no baked geometry -- tag the session map or run "
                  "minimap_geometry.py for its (map, profile) key")
        else:
            med = geometry.reference_static(sid, args.store)
            mm_box = minimap_roi_px(profile, w, h)
            mm_sd = geometry.stability(sid, args.store, med.shape[:2])
            mm_floor = floor_mask(med, sd=mm_sd)
            mm_slab = slab_mask(med, sd=mm_sd)
            mm_sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)
            mm_passable = mm_floor
            geo = geometry.path_of(sid, args.store)
            if geo is not None and geo.is_file():
                z = np.load(geo)
                if "labels" in z.files and z["labels"].shape == mm_floor.shape:
                    mm_passable = cone.passable_from(z["labels"], mm_floor)
                    print("minimap    geometry labels loaded "
                          "(a box stops a ray and is not lit)")
                    # The lighting reference rides along with the labels: it is
                    # the same npz and the same key. Without it the bearing is
                    # whatever the ring fit said, lobe ambiguity and all.
                    mm_light = lighting.reference(z)
                    print("minimap    lighting reference loaded, lobes resolved "
                          f"against the drawn light ({lighting.LIGHTING_VERSION})"
                          if mm_light is not None else
                          "minimap    geometry predates the two-state reference "
                          "-- bearings keep their lobe ambiguity")
                else:
                    print("minimap    geometry present but unusable -- "
                          "floor only, which under-claims")
            else:
                print("minimap    no geometry npz -- floor only, which under-claims")

    ctx = OverlayContext(profile=profile, templates=templates, width=w, height=h,
                         kf_mask=kf_mask, min_confidence=args.min_confidence,
                         min_margin=args.min_margin, spans=spans,
                         mm_box=mm_box, mm_floor=mm_floor, mm_slab=mm_slab,
                         mm_passable=mm_passable, mm_sgray=mm_sgray,
                         mm_static=med if mm_box is not None else None,
                         mm_light=mm_light)
    ctx.mm_apply_lifecycle = args.minimap_lifecycle
    # Capture stalls are a property of the SOURCE, read once from stored
    # primitives rather than measured per frame here -- see `stalls`. None
    # means the session has no primitives table, which is unknown rather than
    # "no stalls", and the diagnostic records which of the two it is.
    ctx.mm_stalls = stalls.for_session(store, sid, _date_of(manifest))
    if ctx.mm_stalls is None:
        print("stalls     no l1/primitives for this session -- capture stalls "
              "UNKNOWN; run `reticle ingest`/`segment` to fill them in")
    elif ctx.mm_stalls:
        print(f"stalls     {len(ctx.mm_stalls)} capture stall(s), "
              f"{stalls.total_ms(ctx.mm_stalls) / 1000:.1f}s "
              f"({stalls.STALL_VERSION}) -- those frames read as stale")

    if args.minimap_events:
        import json
        with Path(args.minimap_events).open(encoding="utf-8") as events_file:
            ctx.mm_origin_events = tuple(json.loads(line) for line in events_file if line.strip())
        if any(event.get("session") != sid for event in ctx.mm_origin_events):
            raise SystemExit("minimap origin events belong to another session")

    out = Path(args.out) if args.out else Path.cwd() / f"overlay_{sid}_{int(t_from)}ms.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit(f"refusing to overwrite evidence: {out}")
    diagnostic_file = None
    if args.minimap_diagnostics:
        import hashlib
        import json
        from .track import TRACK_VERSION
        from .minimap_diagnostics import DIAGNOSTICS_VERSION
        diagnostic_path = out.with_suffix(".minimap.jsonl")
        diagnostic_file = diagnostic_path.open("x", encoding="utf-8")
        producers = ("cli.py", "minimap.py", "track.py", "cone.py", "lighting.py", "minimap_lifecycle.py",
                     "overlay.py", "minimap_diagnostics.py")
        metadata = {"type": "provenance", "version": DIAGNOSTICS_VERSION,
                    "track_version": TRACK_VERSION, "session": sid,
                    "source": manifest["source"], "hz": args.hz,
                    "widget_width": mm_box[2] - mm_box[0] if mm_box else None,
                    "profile": profile.name, "output_fps": args.fps or args.hz,
                    "apply_lifecycle": args.minimap_lifecycle,
                    "from_ms": t_from, "to_ms": t_to,
                    "producer_sha256": {name: hashlib.sha256(
                        (Path(__file__).parent / name).read_bytes()).hexdigest()
                        for name in producers}}
        geo_path = geometry.path_of(sid, args.store)
        metadata["geometry_sha256"] = (hashlib.sha256(geo_path.read_bytes()).hexdigest()
                                       if geo_path and geo_path.is_file() else None)
        metadata["static_sha256"] = (hashlib.sha256(mm_sgray.tobytes()).hexdigest()
                                     if mm_sgray is not None else None)
        metadata["origin_events"] = ctx.mm_origin_events
        diagnostic_file.write(json.dumps(metadata) + "\n")
    scale = args.scale
    size = (int(w * scale), int(h * scale))
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                             args.fps or args.hz, size)
    if not writer.isOpened():
        raise SystemExit(f"could not open {out} for writing")

    cap = cv2.VideoCapture(str(media))
    next_frame = int(round(t_from / 1000.0 * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, next_frame)
    step_ms = 1000.0 / args.hz
    written = skipped = 0
    t0 = time.perf_counter()
    try:
        t = t_from
        while t < t_to:
            target_frame = int(round(t / 1000.0 * fps))
            if target_frame < next_frame:
                t += step_ms
                continue
            while next_frame < target_frame:
                if not cap.grab():
                    break
                next_frame += 1
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx = next_frame
            next_frame += 1
            observed_t = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if observed_t <= 0 and frame_idx > 0:
                observed_t = frame_idx / fps * 1000.0
            if args.entries_only and kf_roi is not None:
                # Skip frames with an empty feed: for debugging attribution, the
                # frames without an entry are the ones with nothing to look at.
                if not analyse_killfeed(frame, kf_roi, w, h, kf_mask, profile.name):
                    t += step_ms
                    skipped += 1
                    continue
            canvas = draw(frame, observed_t, frame_idx, ctx)
            if diagnostic_file is not None:
                import base64
                row = ctx.mm_diagnostic or {"t_ms": t, "widget": "unavailable",
                                            "reason": "geometry unavailable"}
                row["frame_idx"] = frame_idx
                # Source-derived review crop, captured BEFORE any annotations.
                # Shares this decode; it is not a second detector or media copy.
                if mm_box is not None:
                    x0, y0, x1, y1 = mm_box
                    ok_preview, preview = cv2.imencode(".jpg", frame[y0:y1, x0:x1],
                                                       [cv2.IMWRITE_JPEG_QUALITY, 95])
                    if not ok_preview:
                        raise RuntimeError("could not encode clean minimap preview")
                    row["review_preview"] = "data:image/jpeg;base64," + base64.b64encode(preview).decode("ascii")
                diagnostic_file.write(json.dumps(row, default=lambda v: v.item(),
                                                 allow_nan=False) + "\n")
            if scale != 1.0:
                canvas = cv2.resize(canvas, size, interpolation=cv2.INTER_AREA)
            writer.write(canvas)
            written += 1
            if written % 25 == 0:
                sys.stdout.write(f"\r  {written} frames  {_fmt_hms(t)}")
                sys.stdout.flush()
            t += step_ms
    finally:
        writer.release()
        cap.release()
        if diagnostic_file is not None:
            diagnostic_file.close()
    sys.stdout.write("\r" + " " * 60 + "\r")

    dt = time.perf_counter() - t0
    if not written:
        raise SystemExit("wrote no frames -- is the range inside the capture?")
    print(f"wrote      {written} frames  ({dt:.1f}s)"
          + (f", skipped {skipped} with an empty feed" if skipped else ""))
    print(f"           {out}")
    print(f"           {out.stat().st_size / 1e6:.1f} MB  {size[0]}x{size[1]} "
          f"@ {args.fps or args.hz:g} fps")
    print("\ngreen = player kill, red = player death, grey = not the player,")
    print("amber = an overlay covers the name (attribution refused), magenta = unparsed.")
    if ctx.has_minimap:
        print("on the minimap: yellow = self, green = ally, AMBER = bearing "
              "refused (so no")
        print("cone was cast), blue tint = the collective observable area.")
    return 0


# --------------------------------------------------------------------------- sql



def cmd_rounds(args) -> int:
    """Stage 05: derive the round table from stored L1, and score win rates.

    Never opens the video -- everything comes from the HUD reads, so adding a
    fact and rebuilding the whole history costs milliseconds.
    """
    store = Store(args.store)
    sessions = ([_resolve_session(store, args.session)] if args.session
                else sorted(store.sessions(), key=lambda m: m["source"]["filename"]))
    every: list[dict] = []
    print(f"{'session':14s} {'map':8s} {'rounds':>6s} {'side':>6s} {'W-L':>7s}  {'K/D':>8s}")
    for man in sessions:
        sid, date = man["session_id"], _date_of(man)
        path = store.hud_path(sid, date)
        if not path.is_file():
            continue          # never had `hud` run, or has no killfeed ROI
        import pyarrow.parquet as pq
        hud = pq.read_table(path)
        rs = build_rounds(hud)
        if not rs:
            continue
        mp = next((t.split(":", 1)[1] for t in man.get("tags", []) if t.startswith("map:")), "?")
        for r in rs:
            r["map"] = mp
            r["session_id"] = sid
        every += rs
        store.write_rounds(rs, sid, date)
        st_list = stalls.for_session(store, sid, date)
        _gt = gametime.build_session_gametime(sid, hud, rs, stall_list=st_list)
        won = [r["won"] for r in rs if r["won"] is not None]
        # `player_side` is structural now (rounds.PLAYER_SIDE). The statistical
        # inference rides alongside: `~` where it abstained, `!` where it
        # actively disagreed -- and a `!` is worth opening the capture for.
        chk = rs[0]["side_inferred"]
        mark = "" if chk == rs[0]["player_side"] else ("~" if chk == "abstain" else "!")
        print(f"{sid:14s} {mp:8s} {len(rs):6d} {rs[0]['player_side'] + mark:>6s} "
              f"{sum(won):3d}-{len(won) - sum(won):<3d}  "
              f"{sum(r['player_kills'] for r in rs):3d}/{sum(r['player_deaths'] for r in rs):<4d}")

    if not every:
        raise SystemExit("no rounds -- has `hud` been run?")
    s_ = summarise(every)
    print()
    print(f"{len(every)} rounds, {s_['n_rounds']} with a known outcome, "
          f"baseline win rate {s_['baseline'] * 100:.1f}%")
    print()
    print("Win rate given each round fact. Lift is against that baseline; the")
    print("interval is Wilson 95%. These are hypotheses to check against more")
    print("data, not findings -- with this many facts some will look real by chance.")
    print()
    print(f"  {'fact':24s} {'n':>4s} {'win%':>6s} {'lift':>7s}   95% CI")
    for f in s_["facts"]:
        flag = " " if f["lo"] <= s_["baseline"] <= f["hi"] else "*"
        print(f"{flag} {f['fact']:24s} {f['n']:4d} {f['rate'] * 100:5.1f}% "
              f"{f['lift'] * 100:+6.1f}   [{f['lo'] * 100:3.0f}-{f['hi'] * 100:3.0f}]")
    print()
    print("* marks an interval that excludes the baseline.")
    if args.by_map:
        print()
        print("By map (cells go thin fast -- read n before the rate):")
        for mp in sorted({r["map"] for r in every}):
            sub = [r for r in every if r["map"] == mp]
            sm = summarise(sub)
            if not sm["n_rounds"]:
                continue
            print()
            print(f"  {mp}  ({sm['n_rounds']} rounds, baseline {sm['baseline'] * 100:.0f}%)")
            for f in sm["facts"][:4]:
                print(f"    {f['fact']:24s} {f['n']:3d} {f['rate'] * 100:5.1f}% "
                      f"{f['lift'] * 100:+6.1f}")
    return 0


def cmd_lifetimes(args) -> int:
    """Round entity lifetimes from stored ally icons, rounds and roster. No video.

    Writes `round_entity` events; see `reticle/round_entities.py`.
    """
    import hashlib
    import json

    from .round_entities import ROUND_ENTITY_VERSION, session_lifetimes
    from .round_lifetimes import ROUND_LIFETIME_VERSION

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid, date = manifest["session_id"], _date_of(manifest)
    events = store.read_events("ally_icon", sid)
    if not events:
        raise SystemExit(f"no ally_icon events for {sid} -- "
                         f"run `reticle scan {sid} --only ally_icon --ally-hz 15`")
    source_revision = hashlib.sha256(
        store.events_path("ally_icon", sid).read_bytes()).hexdigest()
    # A new observation revision invalidates this derived association.
    path = store.events_path("round_entity", sid)
    stamped = None
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            first = json.loads(f.readline() or "{}")
        stamped = (first.get("round_entity_version"), first.get("round_lifetime_version"),
                   first.get("ally_icon_revision"))
    if stamped == (ROUND_ENTITY_VERSION, ROUND_LIFETIME_VERSION,
                   source_revision) and not args.force:
        print(f"cache hit  session {sid} already has round entities at "
              f"{ROUND_ENTITY_VERSION} / {ROUND_LIFETIME_VERSION}; --force to recompute")
        return 0
    rounds = build_rounds(store.read_hud(sid, date))
    roster = None
    if store.has_roster(sid, date):
        t = store.read_roster(sid, date)
        roster = {"t_ms": t.column("t_ms").to_pylist(),
                  "alive_ally": t.column("alive_ally").to_pylist()}
    box = minimap_roi_px(get_profile(manifest["source_profile"]),
                         int(manifest["source"]["width"]),
                         int(manifest["source"]["height"]))
    rows = session_lifetimes(sid, events, rounds, widget_scale(box[2] - box[0]),
                             roster, source_revision)
    out = store.write_events("round_entity", sid, rows)
    cov = rows[0]
    ents = [r for r in rows if r["kind"] == "entity"]
    by_family = Counter(e["family"] for e in ents)
    print(f"session    {sid}  ally_icon at {events[0].get('hz')} Hz")
    print(f"rounds     {cov.get('rounds', 0)} associated, "
          f"{cov.get('frames', 0)} frames, {cov.get('absent_frames', 0)} widget-absent")
    print(f"entities   {len(ents)}  " + "  ".join(f"{k} {v}" for k, v in sorted(by_family.items())))
    print(f"wrote      {out}")
    return 0


def cmd_belief(args) -> int:
    """Recompute the position belief from stored data. Opens no video.

    The belief is not stored, for the reason `filter_track` is not: it is cheap,
    and keeping the raw reads lets a later change to the law or to the evidence
    be replayed without a re-decode.
    """
    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid, date = manifest["session_id"], _date_of(manifest)
    rows = sorted(store.read_minimap(sid, date).to_pylist(),
                  key=lambda r: r["t_ms"])
    if len(rows) < 2:
        raise SystemExit(f"no minimap positions for {sid}")
    times = [r["t_ms"] for r in rows]
    step = float(np.median(np.diff(times)))
    raw = [(r["t_ms"], r["self_x"], r["self_y"]) for r in rows]

    box = minimap_roi_px(get_profile(manifest["source_profile"]),
                         int(manifest["source"]["width"]),
                         int(manifest["source"]["height"]))
    scale = widget_scale(box[2] - box[0])
    reachable = None
    # Admit the fit error either side: a centre one fit error outside the
    # painted floor is a measurement at the boundary, not a claim that the
    # player stands in a wall.
    with np.load(geometry.require(sid, store.root)) as z:
        if "shade_kind" in z:
            reachable = art_floor(z["shade_kind"],
                                  dilate=_odd(2 * FIT_ERR_PX * scale + 1))
    try:
        voids = round_voids(store.read_rounds(sid, date).to_pylist())
    except Exception:
        voids = []

    fixes = resolve(raw, step, scale, absent_t=absent_instants(rows),
                    voids=voids, reachable=reachable)
    n = len(fixes)
    by = Counter(f.source for f in fixes)
    inferred = [f for f in fixes if f.x is not None and not f.observed]
    print(f"session    {sid}  {n} sampled instants, step {step:.1f} ms")
    print(f"producer   {BELIEF_VERSION}  scale {scale:.3f}  "
          f"{len(voids)} voids  floor {'yes' if reachable is not None else 'NO'}")
    for k in ("observed", "interpolated", "held", "unresolved"):
        print(f"  {k:12s} {by[k]:6d}  {by[k] / n * 100:5.1f}%")
    believed = n - by["unresolved"]
    print(f"  {'believed':12s} {believed:6d}  {believed / n * 100:5.1f}%   "
          f"(observed coverage is {by['observed'] / n * 100:.1f}% and the two "
          f"are never summed)")
    if inferred:
        r = np.array([f.radius_px for f in inferred])
        print(f"inferred   radius px median {np.median(r):.1f}  "
              f"p90 {np.percentile(r, 90):.1f}  max {r.max():.1f}")
    reasons = Counter(f.reason for f in fixes if f.reason)
    for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {why:16s} {count:6d}")
    unresolved = sum(1 for f in fixes if f.source == "unresolved")
    unreasoned = sum(1 for f in fixes if f.source == "unresolved" and not f.reason)
    if unreasoned:
        print(f"WARNING    {unreasoned} unresolved instants carry no reason")
    elif unresolved:
        print("every unresolved instant carries a reason")
    return 0


def cmd_audit(args) -> int:
    """Adjudicate stored independent observations without decoding."""
    import json
    import pyarrow.parquet as pq
    from .reconciliation import (adjudicate_scoreboard_credits, audit_scoreline,
                                 audit_roster_deltas, killfeed_health)

    store = Store(args.store)
    sessions = ([_resolve_session(store, args.session)] if args.session else store.sessions())
    reports = []
    for man in sessions:
        sid, date = man['session_id'], _date_of(man)
        hp, rp = store.hud_path(sid,date), store.roster_path(sid,date)
        if not hp.is_file():
            continue
        hud = pq.ParquetFile(hp).read()
        roster = pq.ParquetFile(rp).read() if rp.is_file() else None
        score, counts = audit_scoreline(hud), audit_roster_deltas(hud,roster)
        kf = killfeed_health(hud)
        scoreboard_observations = store.read_events('scoreboard', sid)
        scoreboard = adjudicate_scoreboard_credits(scoreboard_observations)
        scoreboard_summary = {
            'observations': sum(r.get('kind') == 'row_observation'
                                for r in scoreboard_observations),
            'rows_adjudicated': len(scoreboard),
            'credits_resolved': sum(r['credits'] is not None for r in scoreboard),
            'identities_resolved': sum(r['player_id'] is not None for r in scoreboard),
            'credit_disagreements': sum(r['credit_status'] == 'candidate_disagreement'
                                        for r in scoreboard),
            'identity_disagreements': sum(r['identity_status'] == 'disagreement'
                                          for r in scoreboard),
        }
        reports.append(dict(session_id=sid, scoreline=score, roster=counts,
                            killfeed=kf,
                            scoreboard_credits=scoreboard,
                            scoreboard_summary=scoreboard_summary,
                            audit_version='audit-0.4.0',
                            hud_metadata={k.decode():v.decode() for k,v in (hud.schema.metadata or {}).items()},
                            roster_metadata={k.decode():v.decode() for k,v in
                                             ((roster.schema.metadata or {}) if roster is not None else {}).items()},
                            roster_current=store.has_roster(sid,date)))
        print(f"{sid}: score boundaries {score['raw_boundaries']} raw / "
              f"{score['confirmed_boundaries']} confirmed; roster {counts['counts']}")
        print(f"           killfeed {kf.get('counted',0)} counted, "
              f"{len(kf.get('no_divider',[]))} never formed a divider, "
              f"{len(kf.get('over_long',[]))} over-long "
              f"({kf.get('over_long_inside_frozen',0)} on a frozen frame); "
              f"{kf.get('frozen_seconds',0)}s frozen")
        print(f"           scoreboard credits {scoreboard_summary['credits_resolved']}/"
              f"{scoreboard_summary['rows_adjudicated']} adjudicated rows; "
              f"{scoreboard_summary['credit_disagreements']} candidate disagreements; "
              f"identities {scoreboard_summary['identities_resolved']} resolved / "
              f"{scoreboard_summary['identity_disagreements']} disagreements")
    target = Path(args.out) if args.out else store.root / 'analysis' / (
        f"reconciliation-{sessions[0]['session_id']}.json" if args.session else 'reconciliation.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(f"diagnostic report: {target}")
    return 0


def cmd_coach(args) -> int:
    """Build player events and an honest probability-readiness report from L1."""
    from .coaching import run_coaching

    store = Store(args.store)
    sessions = ([_resolve_session(store, args.session)] if args.session
                else store.sessions())
    out = Path(args.out) if args.out else store.root / "analysis" / "coaching"
    if args.session and not args.out:
        out = out / sessions[0]["session_id"]
    report = run_coaching(store, sessions, out)
    print(f"{report['n_events']} player events; {report['n_rounds']} eligible rounds "
          f"in {report['n_sessions']} sessions")
    print(f"probability evaluation: {report['status']}")
    if report['status'] == 'insufficient_data':
        print("Need at least 3 sessions with current HUD/roster and 30 training rounds "
              "with both outcomes per held-out fold.")
    else:
        print(f"held-out Brier: {report['brier']:.4f}; "
              f"training-base-rate Brier: {report['baseline_brier']:.4f}")
    print(f"{report['n_review_windows']} review windows; "
          f"events, states, predictions, review index and audit: {out}")
    return 0


def cmd_dashboard(args) -> int:
    """Locate, open, or stream the interactive tactical coaching dashboard."""
    store = Store(args.store)
    p = store.root / "notes" / "coaching_dashboard.html"
    if not p.is_file():
        raise SystemExit(f"dashboard HTML not found at {p}")
    print(f"Tactical Coaching Dashboard: {p}")

    if getattr(args, "serve", False):
        import http.server
        import socketserver
        import urllib.parse
        import re
        import webbrowser

        port = args.port
        html_path = p
        videos_dir = Path(args.videos_dir)

        class RangeHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                req_path = urllib.parse.unquote(parsed.path)

                if req_path in ("/", "/index.html"):
                    content = html_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return

                if req_path.startswith("/video/"):
                    fname = req_path[len("/video/"):].lstrip("/\\")
                    target = videos_dir / fname
                    if not target.is_file():
                        target = Path(fname)
                    if not target.is_file():
                        self.send_error(404, f"Video not found: {fname}")
                        return
                    self._serve_range(target)
                    return

                self.send_error(404, "Not Found")

            def do_HEAD(self):
                parsed = urllib.parse.urlparse(self.path)
                req_path = urllib.parse.unquote(parsed.path)

                if req_path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(html_path.stat().st_size))
                    self.end_headers()
                    return

                if req_path.startswith("/video/"):
                    fname = req_path[len("/video/"):].lstrip("/\\")
                    target = videos_dir / fname
                    if not target.is_file():
                        target = Path(fname)
                    if not target.is_file():
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(target.stat().st_size))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    return

                self.send_error(404)

            def _serve_range(self, file_path: Path):
                file_size = file_path.stat().st_size
                range_header = self.headers.get("Range")

                if range_header:
                    m = re.match(r"^bytes=(\d+)-(\d+)?$", range_header.strip())
                    if m:
                        start = int(m.group(1))
                        end = int(m.group(2)) if m.group(2) else file_size - 1
                        if start < file_size and end < file_size and start <= end:
                            length = end - start + 1
                            self.send_response(206)
                            self.send_header("Content-Type", "video/mp4")
                            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                            self.send_header("Content-Length", str(length))
                            self.send_header("Accept-Ranges", "bytes")
                            self.end_headers()
                            try:
                                with open(file_path, "rb") as f:
                                    f.seek(start)
                                    rem = length
                                    while rem > 0:
                                        chunk = f.read(min(rem, 65536))
                                        if not chunk:
                                            break
                                        self.wfile.write(chunk)
                                        rem -= len(chunk)
                            except (ConnectionResetError, BrokenPipeError):
                                pass
                            return

                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                try:
                    with open(file_path, "rb") as f:
                        rem = file_size
                        while rem > 0:
                            chunk = f.read(min(rem, 65536))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            rem -= len(chunk)
                except (ConnectionResetError, BrokenPipeError):
                    pass

            def log_message(self, format, *args):
                pass

        class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        server_address = ("127.0.0.1", port)
        try:
            httpd = ThreadingServer(server_address, RangeHandler)
        except OSError as e:
            raise SystemExit(f"Could not bind to port {port}: {e}")

        url = f"http://127.0.0.1:{port}"
        print(f"Serving dashboard at: {url}")
        print(f"Streaming video from: {videos_dir} (HTTP 206 Range enabled)")
        print("Press Ctrl+C to stop.")

        if args.open:
            webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped.")
            httpd.server_close()
        return 0

    if args.open:
        import webbrowser
        webbrowser.open(p.as_uri())
    return 0


def cmd_economy(args) -> int:
    """Apply an explicit fact document; does not read or infer from video."""
    import json
    from .economy import run_document

    source = Path(args.facts)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        result = run_document(document)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SystemExit(f"economy refused {source}: {exc}") from exc
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(f"{len(result['transactions'])} transactions; economy ledger: {target}")
    else:
        print(rendered)
    return 0


def cmd_ability_coverage(args) -> int:
    """Index ability evidence and property coverage without decoding media."""
    from .ability_coverage import run

    bundle = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    target = Path(args.out) if args.out else Path(args.store) / "analysis" / "ability-coverage"
    print(f"{summary['definitions']} abilities; {summary['demo_sessions']} demo sessions; "
          f"{summary['source_windows']} source windows")
    print(f"coverage {summary['coverage_statuses']}; conflicts {summary['conflicts']}")
    print(f"ability coverage: {target}")
    return 0


def cmd_ability_timeline(args) -> int:
    """Build bounded ability-use claims, optionally materializing tray reads."""
    from .ability_timeline import run

    bundle, materialized = run(args.store, args.out, materialize=args.materialize,
                               step_s=args.step)
    if materialized:
        print(f"materialized {materialized['candidates']} candidates across "
              f"{len(materialized['sessions'])} demos")
    summary = bundle["manifest"]["summary"]
    target = Path(args.out) if args.out else Path(args.store) / "analysis" / "ability-timeline"
    print(f"{summary['use_claims']} use claims across {summary['sessions_with_claims']} sessions; "
          f"{summary['suspect_candidates']} suspect; {summary['conflicts']} conflicts")
    print(f"ability timeline: {target}")
    return 0


def cmd_ability_entities(args) -> int:
    """Build alternative ability component, entity, and property hypotheses."""
    from .ability_entities import run

    bundle, target = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    print(f"{summary['components']} components; {summary['component_parent_edges']} parent edges; "
          f"{summary['entity_hypotheses']} entity hypotheses")
    print(f"{summary['supported_parent_edges']} supported parent edges; "
          f"{summary['review_windows']} unresolved review windows")
    print(f"ability entities: {target}")
    return 0


def cmd_ability_light(args) -> int:
    """Store the drawn light at every ability candidate's instant.

    `lighting.raw_lit` on a sparse set of frames. Nothing here decides;
    `adjudication.ability` reads the `ability_light` events to refuse
    drawn-light candidates.
    """
    import cv2
    import numpy as np

    from . import geometry, lighting
    from .adjudication.ability import _components, _labels
    from .version import ABILITY_LIGHT_VERSION

    store = Store(args.store)
    root = store.root
    times = {}
    for c in _components(root, _labels(root)):
        times.setdefault(c["session_id"], set()).add(float(c["observed_t_ms"]))
    sessions = sorted(times) if args.all else [args.session]
    for sid in sessions:
        if sid not in times:
            print(f"{sid}: no ability candidates")
            continue
        man = geometry.manifest(sid, root)
        geo = geometry.path_of(sid, root)
        if man is None or geo is None or not geo.is_file():
            print(f"{sid}: no baked geometry -- skipped")
            continue
        with np.load(geo) as z:
            ref = lighting.reference(z)
        if ref is None:
            print(f"{sid}: geometry has no lighting reference -- skipped")
            continue
        src = man["source"]
        x0, y0, x1, y1 = minimap_roi_px(get_profile(man["source_profile"]),
                                        int(src["width"]), int(src["height"]))
        common = {"session_id": sid, "source": "minimap",
                  "ability_light_version": ABILITY_LIGHT_VERSION,
                  "lighting_version": lighting.LIGHTING_VERSION,
                  "geometry_key": geometry.key_of(sid, root)}
        rows, refused = [], Counter()
        cap = cv2.VideoCapture(src["path"])
        for t in sorted(times[sid]):
            cap.set(cv2.CAP_PROP_POS_MSEC, t)
            ok, frame = cap.read()
            crop = frame[y0:y1, x0:x1] if ok else None
            if crop is None or crop.shape[:2] != ref.known.shape:
                reason = "unreadable_frame" if crop is None else "geometry_size_mismatch"
                refused[reason] += 1
                rows.append({**common, "kind": "frame", "t_ms": t, "raw_lit": None,
                             "reason": reason})
                continue
            rows.append({**common, "kind": "frame", "t_ms": t,
                         "raw_lit": lighting.pack_mask(lighting.raw_lit(crop, ref)),
                         "raw_dark": lighting.pack_mask(lighting.raw_dark(crop, ref)),
                         "reason": None})
        cap.release()
        rows.insert(0, {**common, "kind": "coverage", "frames": len(rows),
                        "refused_reasons": dict(sorted(refused.items()))})
        out = store.write_events("ability_light", sid, rows)
        print(f"{sid}: {len(rows) - 1} frames, refused {dict(refused)} -> {out}")
    return 0


def cmd_ability_gallery(args) -> int:
    """Build phase galleries and score identity on held-out sessions."""
    from .ability_gallery import run

    bundle, target = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    print(f"{summary['named_examples']} named examples ({summary['examples_with_trace']} with a "
          f"series trace) over {summary['abilities']} abilities; {summary['gallery_rows']} gallery rows")
    for row in bundle["evaluation"]:
        scores = ", ".join(
            f"{name} {value['balanced_accuracy']}" if value["balanced_accuracy"] is not None
            else f"{name} n/a" for name, value in sorted(row["scores"].items()))
        print(f"  test {row['test_session']} ({row['agent']}, n={row['n_test']}): {scores}")
    print(f"{summary['scored_contrasts']} scored contrasts, "
          f"{summary['excluded_contrasts']} excluded for want of a held-out split")
    print(f"ability gallery: {target}")
    return 0


def cmd_ability_capture(args) -> int:
    """Rank review work and issue capture cards for demonstrated gaps only."""
    import json as _json

    from .ability_capture import run
    from .adjudication.capture import record_take

    if args.record_take:
        take = _json.loads(Path(args.record_take).read_text(encoding="utf-8"))
        row = record_take(args.store, take["take_id"], take.get("session_id"),
                          take["outcomes"], take.get("operator_note", ""))
        print(f"recorded take {row['take_id']} with {len(row['claims'])} claim(s); "
              f"a claim is not a result -- rerun to see what the store can corroborate")

    bundle, target = run(args.store, args.out)
    summary = bundle["manifest"]["summary"]
    print(f"{summary['review_items']} review items at zero recorded seconds; "
          f"{summary['deferred_requests']} deferred requests")
    print(f"{summary['capture_cards']} capture cards in {summary['capture_batches']} takes, "
          f"{summary['requested_recorded_s']:.0f}s recorded")
    for card in bundle["cards"]:
        print(f"  {card['rank']}. {card['ability_id']} ({card['cost']['recorded_s']:.0f}s) "
              f"-- {card['named_missing_discriminator']}")
    for verdict in bundle["takes"]:
        print(f"  take {verdict['take_id']} {verdict['capture_request_id']}: "
              f"{verdict['verdict']} -- {verdict['reason']}")
    print(f"ability capture queue: {target}")
    return 0


def cmd_ability_phases(args) -> int:
    """Segment deployed entities into phases and offer causes for each change."""
    from .ability_phases import run

    bundle, target = run(args.store, args.out)
    s = bundle["manifest"]["summary"]
    print(f"{s['entities']} entities, {s['entities_with_a_transition']} of which transform; "
          f"{s['transitions']} transitions {s['by_direction']}")
    print(f"{s['resolved']} resolved by a cause, {s['unexplained']} unexplained "
          f"(a flag, not a silent row)")
    print(f"ability phases: {target}")
    return 0


def cmd_refine(args) -> int:
    """Preview or densely read explicitly selected review windows."""
    import hashlib
    import json
    from .refine import iter_windows
    from .refinement import plan_refinement, save_refinement
    from .fingerprint import content_key
    from .profiles import template_key

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    bundle = Path(args.bundle) if args.bundle else store.root / "analysis" / "coaching"
    if args.max_frames <= 0:
        raise SystemExit("--max-frames must be positive")
    try:
        plan = plan_refinement(store, manifest, bundle, args.review_id, args.max_seconds)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{len(plan['review_ids'])} review windows -> {len(plan['spans_ms'])} merged intervals; "
          f"{plan['seconds']:.3f}s at native rate (limit {args.max_frames} frames)")
    for a, z in plan['spans_ms']:
        print(f"  {a/1000:.3f}-{z/1000:.3f}s")
    if not args.execute:
        print("Preview only. Pass --execute to decode these intervals into separate HUD evidence.")
        return 0
    media = Path(plan['source_path'])
    if not media.is_file():
        raise SystemExit(f"source media has moved: {media}")
    if content_key(media) != manifest['source'].get('content_key'):
        raise SystemExit("source identity changed; refinement requires the original capture")
    profile = get_profile(manifest['source_profile'])
    if killfeed_roi(profile) is not None and store.read_kf_mask(manifest['session_id']) is None:
        raise SystemExit("cached killfeed mask is missing; run hud first (refine will not calibrate across the capture)")
    reader = _HudPass(store, manifest, profile,
                      argparse.Namespace(min_confidence=0.82, min_margin=0.05, hz=0))
    assets = [Templates.path_for(profile.name),
              me_template_path(profile.name),
              store.kf_mask_path(manifest['session_id'])]
    plan['reader_configuration'] = dict(hud_version=HUD_VERSION, min_confidence=0.82,
                                        min_margin=0.05, max_frames=args.max_frames,
                                        assets_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in assets if p.is_file()})
    t0 = time.perf_counter()
    samples = iter_windows(str(media), plan['spans_ms'], args.max_frames)
    try:
        for sample in samples:
            reader.feed(sample)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        samples.close()
    if not reader.rows:
        raise SystemExit("no frames decoded; no refinement artifact written")
    key = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
    out = Path(args.out) if args.out else store.root / "analysis" / "refinement" / manifest['session_id'] / f"{key}.json"
    save_refinement(out, plan, reader.rows)
    print(f"{len(reader.rows)} dense HUD observations in {time.perf_counter()-t0:.2f}s: {out}")
    return 0


def cmd_acquisition_plan(args) -> int:
    """Validate a machine-readable evidence contract without opening media."""
    import json
    from .acquisition import write_plan

    try:
        plan = write_plan(args.spec, args.out)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(plan, sort_keys=True, indent=2, allow_nan=False))
    return 0


def cmd_capabilities(args) -> int:
    """Print what the shipped readers are validated to do, and what is withheld.

    Stored-data-only: it declares, it does not measure. The measurement is
    `reticle fidelity-check`.
    """
    from .capabilities import (CAPABILITIES_VERSION, FROZEN_EVIDENCE,
                               builtin_capabilities, unvalidated)

    declared = builtin_capabilities()
    print(f"{CAPABILITIES_VERSION}   evidence: {FROZEN_EVIDENCE}")
    print(f"\nDECLARED ({len(declared)} reader(s))")
    for name, capability in sorted(declared.items()):
        tiers = ", ".join(f"{t.name}@{'native' if t.hz is None else f'{t.hz:g}Hz'}"
                          for t in capability.tiers)
        print(f"  {name}")
        print(f"    properties  {', '.join(capability.properties)}")
        print(f"    tiers       {tiers}")
        print(f"    regimes     {', '.join(capability.regimes)}")
        print(f"    absence     {capability.negative_evidence}")
    withheld = unvalidated()
    print(f"\nWITHHELD ({len(withheld)})")
    for key, why in sorted(withheld.items()):
        print(f"  {key}")
        print(f"    {why}")
    return 0


def cmd_fidelity_check(args) -> int:
    """Run the frozen P3 comparison: reference fidelity against cheaper tiers.

    This opens the source, so it is not a stored-data command. It reads the
    frozen window contract, never writes to it, and refuses a session other
    than the one the windows were reviewed on -- a frozen evaluation moved to
    another capture is a new evaluation with an old name.
    """
    import json
    from .fidelity import Tier, compare, load_windows

    store = Store(args.store)
    try:
        frozen = load_windows(args.windows)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    manifest = _resolve_session(store, args.session or frozen["session_id"])
    sid = manifest["session_id"]
    if sid != frozen["session_id"]:
        raise SystemExit(f"these windows were reviewed on {frozen['session_id']}, "
                         f"not {sid}")
    profile = get_profile(manifest["source_profile"])
    spans = _active_spans(store, sid, _date_of(manifest))
    ctx = SessionContext(store=store, manifest=manifest, profile=profile, spans=spans)

    tiers = [Tier("native", None)] + [Tier(f"{hz:g}hz", hz) for hz in args.hz]
    print(f"session    {sid}  contract {frozen['contract']} frozen {frozen['frozen_on']}")
    print(f"windows    {len(frozen['windows'])}, "
          f"{sum(w['t1_ms'] - w['t0_ms'] for w in frozen['windows']) / 1000:.1f}s reviewed")
    print(f"tiers      {', '.join(t.name for t in tiers)}  via {args.transport}")
    result = compare(ctx, frozen, tiers, transport=args.transport)

    print()
    print("killfeed presence is the ADJUDICATED account -- entries that "
          "persisted across frames;")
    print("the per-frame column beside it is what the reader claimed frame by "
          "frame.")
    print("minimap coverage excludes widget-absent frames; it is diagnostic and "
          "has no frozen PASS threshold.")
    print()
    print(f"{'tier':>8}  {'frames':>7} {'wall_s':>7} {'cost':>6}  "
          f"{'kf_recall':>9} {'kf_fp':>5} {'per_frame_fp':>12}  "
          f"{'mm_cover':>8} {'mm_agree':>8}  verdict")
    for row in result["tiers"]:
        recall = row["killfeed"]["pooled_presence_recall"]
        agree = row.get("minimap_agreement", {}).get("agreement_fraction")
        coverage = row["minimap_coverage"]["eligible_coverage_fraction"]
        verdict = ("reference" if row["is_reference"]
                   else ("PASS" if row["verdict"]["pass"]
                         else "FAIL " + ",".join(row["verdict"]["failed"])))
        print(f"{row['tier']:>8}  {row['retrieved_frames']:>7} "
              f"{row['wall_seconds']:>7.2f} "
              f"{(row['cost_ratio_vs_reference'] or 0):>6.3f}  "
              f"{('n/a' if recall is None else f'{recall:9.4f}'):>9} "
              f"{row['killfeed']['false_positive_instants']:>5} "
              f"{row['killfeed_per_frame']['false_positive_instants']:>12}  "
              f"{('n/a' if coverage is None else f'{coverage:8.4f}'):>8} "
              f"{('n/a' if agree is None else f'{agree:8.4f}'):>8}  {verdict}")
    print()
    for row in result["tiers"]:
        tr = row["killfeed_tracks"]
        print(f"{row['tier']:>8}  entry tracks {tr['counted']:2d} counted, "
              f"{tr['refused']['single_frame']:2d} single-frame and "
              f"{tr['refused']['no_persistence']:2d} refused for no persistence")
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, sort_keys=True, indent=2,
                                     allow_nan=False), encoding="utf-8")
        print(f"\nwrote      {target}")
    return 0


def cmd_doctor(args) -> int:
    """Structural checks on the REPO, the half `status` does not cover.

    `status` says what is in the store. This says what shape the codebase is
    in, which nothing computed until `floor_mask` had been forked for ten days
    while the check meant to catch it passed clean.
    """
    from .doctor import main as doctor_main

    return doctor_main(["--store", str(args.store)])


def cmd_domain(args) -> int:
    """The domain registry: what is true of the GAME, not of this pipeline.

    One place, one TOML table per fact, cited by a bracketed `domain:` token
    rather than restated. `--check` validates the schema and reports facts nothing cites;
    `doctor`'s DOMAIN check runs the same validation.
    """
    from .domain import main as domain_main

    argv = []
    if args.domain:
        argv.append(args.domain)
    if args.id:
        argv += ["--id", args.id]
    if args.subject:
        argv += ["--subject", args.subject]
    if args.uncited:
        argv.append("--uncited")
    if args.check:
        argv.append("--check")
    return domain_main(argv)


def cmd_domain_hypothesis(args) -> int:
    """Review a pinned stored-data proposal without changing accepted facts."""
    from .domain_learning import publish
    document = json.loads(args.proposal.read_text(encoding="utf-8"))
    path, report = publish(document, args.output)
    print(f"Review: {path / 'review.md'}")
    print(f"JSON: {path / 'report.json'}")
    print(f"Valid: {report['valid']}; independent support: {len(report['independent_support'])}; "
          f"refusals: {len(report['errors'])}")
    return 0 if report["valid"] else 1


def cmd_ownership(args) -> int:
    """Who owns a question, and what that owner is NOT for.

    Ask it in plain language -- `reticle ownership which agent died` -- and it
    routes to the owner, or to the entry saying nothing owns that yet. The
    negative boundary is the half worth reading: it is what stops `track` being
    selected because the word *track* matched.
    """
    from .ownership import main as ownership_main

    argv = list(args.question or [])
    if args.module:
        argv += ["--module", args.module]
    if args.check:
        argv.append("--check")
    return ownership_main(argv)


def cmd_status(args) -> int:
    """Status, computed from the store rather than written down.

    28.8 KB of CLAUDE.md was status carrying 77 numeric claims, every one a
    snapshot that rots silently. On the day this landed the written status was
    wrong three ways in a single paragraph -- seventeen sessions against 18,
    hud-0.8.1 against hud-0.9.0, nine of thirteen exact against 9 of 17. A fact
    that is computed cannot disagree with the code.
    """
    from .status import collect, render

    data = collect(Store(args.store))
    text = render(data, markdown=args.markdown or args.write)
    if args.write:
        p = Path(__file__).resolve().parent.parent / "STATUS.md"
        p.write_text(text + chr(10), encoding="utf-8")
        print(f"wrote {p}")
    else:
        print(text)
    return 0


def cmd_metrics(args) -> int:
    """What moved since the last comparable run, and nothing else.

    The companion to `status`: that one computes the present so it cannot rot,
    this one compares it to the past so a silent change cannot pass as one. A
    series where nothing moved prints one line.
    """
    from . import metrics

    print(metrics.report(tool=args.tool, verbose=args.verbose))
    return 0


def cmd_sql(args) -> int:
    import duckdb

    store = Store(args.store)
    con = duckdb.connect()
    made = []
    for view, glob in (("primitives", store.primitives_glob()),
                       ("spans", store.spans_glob()),
                       ("hud", store.hud_glob())):
        try:
            con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{glob}')")
            made.append(view)
        except duckdb.Error:
            pass
    if not made:
        raise SystemExit(f"store has no parquet yet: {store.root}")

    if not args.query:
        print(f"views: {', '.join(made)}")
        for view in made:
            cols = con.execute(f"DESCRIBE {view}").fetchall()
            print(f"\n{view} ({len(cols)} columns)")
            for name, dtype, *_ in cols[:80]:
                print(f"  {name:<26}{dtype}")
        return 0

    try:
        result = con.execute(args.query)
    except duckdb.Error as exc:
        raise SystemExit(f"query failed: {exc}")
    cols = [d[0] for d in result.description]
    rows = result.fetchall()
    widths = [max(len(c), *(len(str(r[i])) for r in rows)) if rows else len(c)
              for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows[: args.limit]:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    if len(rows) > args.limit:
        print(f"... {len(rows) - args.limit} more rows")
    return 0


# --------------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reticle", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default=str(DEFAULT_STORE), help=f"event store root (default {DEFAULT_STORE})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth", help="generate a synthetic clip to test the pipeline")
    s.add_argument("--out"); s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720); s.add_argument("--fps", type=float, default=30.0)
    s.set_defaults(func=cmd_synth)

    s = sub.add_parser("probe", help="fingerprint a video and render ROI overlays")
    s.add_argument("video"); s.add_argument("--profile", default=DEFAULT_PROFILE)
    s.add_argument("--n", type=int, default=8); s.add_argument("--out")
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser("ingest", help="decode a video into L1 primitives")
    s.add_argument("video"); s.add_argument("--profile", default=DEFAULT_PROFILE)
    s.add_argument("--hz", type=float, default=5.0, help="sample rate (default 5)")
    s.add_argument("--max-frames", type=int, default=None, help="stop early, for a quick look")
    s.add_argument("--force", action="store_true", help="re-decode even on a cache hit")
    s.add_argument("--minimap-mode", default=None,
                   help="override the profile's minimap settings, e.g. "
                        "fixed/per_side/uncentered or 'rotating centered'")
    # Free-form and deliberately unvalidated. Anything about the *sitting* that
    # the pixels cannot show has to be written down at ingest or it is gone --
    # the map, whether this followed a break, whether the last match went badly.
    # A tag costs nothing now and cannot be reconstructed later.
    s.add_argument("--tags", default=None,
                   help="comma-separated notes about this session, e.g. "
                        "\"ascent, long-break, reported-last-match\". Free text; "
                        "they land in the manifest and nothing parses them.")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("segment", help="recompute spans from stored L1 (no video)")
    s.add_argument("session", nargs="?"); s.add_argument("--all", action="store_true")
    d = SegmentConfig()
    s.add_argument("--minimap-dchange", type=float, default=d.minimap_dchange_min)
    s.add_argument("--hud-edge", type=float, default=d.hud_edge_min)
    s.add_argument("--active-motion", type=float, default=d.active_motion_min)
    s.add_argument("--smooth", type=int, default=d.smooth_window)
    s.add_argument("--min-span", type=float, default=d.min_span_ms / 1000.0, help="seconds")
    s.add_argument("--show-signals", action="store_true", help="percentiles, for threshold calibration")
    s.set_defaults(func=cmd_segment)

    s = sub.add_parser("inspect", help="summarise the store or one session")
    s.add_argument("session", nargs="?")
    s.add_argument("--spans", type=int, default=0, help="also list the first N spans")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("frames", help="dump labelled frames for eyeballing")
    s.add_argument("session", nargs="?"); s.add_argument("--every", type=float, default=10.0, help="seconds")
    s.add_argument("--out")
    s.set_defaults(func=cmd_frames)

    s = sub.add_parser("hud", help="stage 02: read the scoreline into L1 HUD reads")
    s.add_argument("session", nargs="?")
    s.add_argument("--hz", type=float, default=2.0, help="sample rate (default 2)")
    s.add_argument("--max-frames", type=int, default=None)
    s.add_argument("--min-confidence", type=float, default=0.82,
                   help="reject glyph matches weaker than this (default 0.82)")
    s.add_argument("--min-margin", type=float, default=0.05,
                   help="reject glyphs whose nearest template is not decisively "
                        "nearer than the next digit (default 0.05)")
    s.add_argument("--force", action="store_true", help="re-read even on a cache hit")
    s.set_defaults(func=cmd_hud)

    s = sub.add_parser("scan", help="stages 02 hud + minimap in ONE decode pass")
    s.add_argument("session", nargs="?")
    s.add_argument("--hz", type=float, default=2.0, help="HUD sample rate (default 2)")
    s.add_argument("--minimap-hz", type=float, default=15.0,
                   help="minimap sample rate (default 15)")
    s.add_argument("--min-confidence", type=float, default=0.82)
    s.add_argument("--min-margin", type=float, default=0.05)
    # On by default: pings ride the pass, so the only thing --no-ping saves is
    # the analysis, and decode is 93% of the cost. A corpus re-scan that has to
    # be asked for pings is how the last one finished without any.
    s.add_argument("--no-ping", dest="ping", action="store_false",
                   help="skip the minimap ping reader (it rides this pass free)")
    s.add_argument("--ping-hz", type=float, default=10.0,
                   help="ping sample rate (default 10 -- the lifetime gate "
                        "resolves 7.0s from 10.0s, so this is not a knob to "
                        "lower casually)")
    s.set_defaults(ping=True)
    # Same argument as --no-ping: it rides the HUD's own frames, so skipping it
    # saves one Laplacian per frame and nothing else.
    s.add_argument("--no-lineup", dest="lineup", action="store_false",
                   help="skip naming the ten agents from the top bar; it "
                        "otherwise rides every unnarrowed scan for free")
    s.add_argument("--ally-hz", type=float, default=ALLY_DESCRIPTOR_HZ,
                   help=f"ally icon descriptor rate (default {ALLY_DESCRIPTOR_HZ:g}); "
                        "round lifetimes want the minimap's 15")
    s.add_argument("--only", nargs="+",
                   choices=("hud", "minimap", "ping", "roster", "scoreboard",
                            "ally_icon"),
                   help="run only these readers through the shared pass; roster-only needs no minimap geometry")
    s.add_argument("--no-roster", dest="roster", action="store_false",
                   help="skip the roster alive-count reader (it rides this pass free)")
    s.set_defaults(roster=True)
    s.add_argument("--no-scoreboard", dest="scoreboard", action="store_false",
                   help="skip context-free Tab-scoreboard rows and credit observations")
    s.set_defaults(scoreboard=True)
    s.add_argument("--force", action="store_true", help="re-read even on a cache hit")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("minimap", help="stage 02: player position off the minimap")
    s.add_argument("session", nargs="?")
    s.add_argument("--hz", type=float, default=15.0,
                   help="sample rate (default 15 -- position is a speed measurement, "
                        "2 Hz cannot support one)")
    s.add_argument("--force", action="store_true", help="re-read even on a cache hit")
    s.set_defaults(func=cmd_minimap)

    s = sub.add_parser("glyphs", help="mine digit templates from real footage")
    s.add_argument("video", nargs="+", help="one or more captures to mine")
    s.add_argument("--profile", default=DEFAULT_PROFILE)
    s.add_argument("--every", type=float, default=9.0, help="seconds between samples")
    s.add_argument("--skip", type=int, default=200, help="seconds to skip at the head")
    s.add_argument("--tol", type=float, default=0.06, help="cluster tolerance")
    s.add_argument("--min-count", type=int, default=5)
    s.add_argument("--label", default=None, help="one character per cluster, in montage order")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_glyphs)

    s = sub.add_parser("verify", help="check HUD reads against domain invariants")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("board", help="read the Tab scoreboard and score our K/D against it")
    s.add_argument("session", nargs="?")
    s.add_argument("--hz", type=float, default=2.0, help="sample rate (default 2)")
    s.add_argument("--gap", type=float, default=3.0,
                   help="seconds of absence that ends one opening (default 3)")
    s.add_argument("--max-frames", type=int, default=None)
    s.add_argument("--min-confidence", type=float, default=0.80)
    s.add_argument("--min-margin", type=float, default=0.04)
    s.set_defaults(func=cmd_board)

    s = sub.add_parser("kd", help="running K/D per round, to check against the scoreboard")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_kd)

    s = sub.add_parser("overlay", help="render detections onto the video (debug aid)")
    s.add_argument("session", nargs="?")
    s.add_argument("--from", dest="start", default=None,
                   help="start timestamp: 90, 1:30 or 1:02:03 (default: the beginning)")
    s.add_argument("--to", dest="end", default=None, help="end timestamp")
    s.add_argument("--seconds", type=float, default=60.0,
                   help="length from --from when --to is not given (default 60)")
    s.add_argument("--hz", type=float, default=5.0, help="sample rate (default 5)")
    s.add_argument("--fps", type=float, default=None,
                   help="playback rate of the output (default: same as --hz, so real time)")
    s.add_argument("--scale", type=float, default=1.0, help="output scale (default 1.0)")
    s.add_argument("--no-mask", action="store_true",
                   help="skip overlay-mask calibration (faster, less faithful)")
    s.add_argument("--no-minimap", action="store_true",
                   help="skip the minimap channel (icons, bearings, the "
                        "collective viewcone) -- it needs a static map")
    s.add_argument("--minimap-diagnostics", action="store_true",
                   help="write versioned per-frame track/light evidence beside the video")
    s.add_argument("--minimap-events", help="JSONL of corroborated spatial origin/relocation events")
    s.add_argument("--minimap-lifecycle", action="store_true",
                   help="exclude unexplained appearances from inferred cones; preserve raw candidates")
    s.add_argument("--entries-only", action="store_true",
                   help="only render frames whose killfeed holds an entry")
    s.add_argument("--min-confidence", type=float, default=0.82)
    s.add_argument("--min-margin", type=float, default=0.05)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_overlay)

    s = sub.add_parser("lifetimes", help="round entity lifetimes from stored ally icons (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--force", action="store_true", help="recompute on a cache hit")
    s.set_defaults(func=cmd_lifetimes)

    s = sub.add_parser("belief", help="recompute the self position belief from stored data (no video)")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_belief)

    s = sub.add_parser("audit", help="localize roster/scoreline disagreements from stored data")
    s.add_argument("session", nargs="?")
    s.add_argument("--out", help="diagnostic JSON path")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("coach", help="derive player events, review windows and held-out state estimates")
    s.add_argument("session", nargs="?")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/coaching)")
    s.set_defaults(func=cmd_coach)

    s = sub.add_parser("economy", help="apply an explicit JSON fact stream to the credit ledger")
    s.add_argument("facts", help="JSON file containing teams and ordered operations")
    s.add_argument("--out", help="write the ledger JSON here (default: stdout)")
    s.set_defaults(func=cmd_economy)

    s = sub.add_parser("ability-coverage", help="inventory existing ability evidence without decoding")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-coverage)")
    s.set_defaults(func=cmd_ability_coverage)

    s = sub.add_parser("ability-timeline", help="build bounded ability-use claims")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-timeline)")
    s.add_argument("--materialize", action="store_true",
                   help="read every demo tray before building the stored timeline")
    s.add_argument("--step", type=float, default=0.5,
                   help="tray sampling interval for --materialize (default 0.5s)")
    s.set_defaults(func=cmd_ability_timeline)

    s = sub.add_parser("ability-light", help="store the drawn light at ability candidates (opens media)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session with ability candidates")
    s.set_defaults(func=cmd_ability_light)

    s = sub.add_parser("ability-entities", help="build alternative ability entity hypotheses")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-entities)")
    s.set_defaults(func=cmd_ability_entities)

    s = sub.add_parser("ability-gallery", help="appearance galleries and held-out identity scores")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-gallery)")
    s.set_defaults(func=cmd_ability_gallery)

    s = sub.add_parser("ability-capture", help="targeted capture queue for demonstrated gaps")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-capture)")
    s.add_argument("--record-take", metavar="TAKE.json",
                   help="append one executed take, then rebuild; claims are checked against "
                        "independent evidence rather than believed")
    s.set_defaults(func=cmd_ability_capture)

    s = sub.add_parser("ability-phases", help="entity phases and their transition causes")
    s.add_argument("--out", help="output bundle directory (default: store/analysis/ability-phases)")
    s.set_defaults(func=cmd_ability_phases)

    s = sub.add_parser("refine", help="preview or densely read selected coaching review windows")
    s.add_argument("session")
    s.add_argument("--review-id", action="append", required=True, help="review ID; repeat to merge windows")
    s.add_argument("--bundle", help="coaching bundle directory")
    s.add_argument("--execute", action="store_true", help="decode source pixels after validating the plan")
    s.add_argument("--max-seconds", type=float, default=30.0, help="maximum total merged duration (default: 30)")
    s.add_argument("--max-frames", type=int, default=2000, help="hard native-frame limit; exceeding it refuses")
    s.add_argument("--out", help="dense evidence JSON path")
    s.set_defaults(func=cmd_refine)

    s = sub.add_parser("acquisition-plan",
                       help="validate and plan a JSON evidence-sampling contract")
    s.add_argument("spec", help="JSON file containing capabilities and evidence requests")
    s.add_argument("--out", help="also write the resulting plan JSON here")
    s.set_defaults(func=cmd_acquisition_plan)

    s = sub.add_parser("capabilities",
                       help="what the shipped readers are validated to do")
    s.set_defaults(func=cmd_capabilities)

    s = sub.add_parser("fidelity-check",
                       help="P3: compare cheaper tiers to reference fidelity on "
                            "the frozen source-reviewed windows")
    s.add_argument("session", nargs="?", help="defaults to the session the windows name")
    s.add_argument("--windows", default=str(FROZEN_WINDOWS),
                   help="frozen window contract (default: the shipped reticle/frozen one)")
    s.add_argument("--hz", type=float, nargs="+", default=[15.0, 10.0, 5.0, 2.0],
                   help="candidate tiers to compare against native (default: 15 10 5 2)")
    s.add_argument("--transport", default="seek_windows",
                   choices=["seek_windows", "sequential_grab"],
                   help="decode transport (default: seek_windows)")
    s.add_argument("--out", help="write the full comparison JSON here")
    s.set_defaults(func=cmd_fidelity_check)

    s = sub.add_parser("rounds", help="stage 05: derive rounds and score win rates")
    s.add_argument("session", nargs="?")
    s.add_argument("--by-map", action="store_true", help="also split every fact by map")
    s.set_defaults(func=cmd_rounds)

    s = sub.add_parser("doctor", help="structural checks on the repo "
                       "(duplicates, unwired modules, stale geometry)")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("domain", help="the domain registry -- what is true of "
                       "VALORANT, cited rather than restated")
    s.add_argument("domain", nargs="?", help="limit to one domain file")
    s.add_argument("--id", help="limit to one fact id")
    s.add_argument("--subject", help="limit to facts concerning one subject")
    s.add_argument("--uncited", action="store_true",
                   help="only facts nothing cites")
    s.add_argument("--check", action="store_true",
                   help="validate the registry and its citations")
    s.set_defaults(func=cmd_domain)

    s = sub.add_parser("domain-hypothesis", help="review a pinned stored-data domain proposal")
    s.add_argument("proposal", type=Path)
    s.add_argument("--output", type=Path, required=True)
    s.set_defaults(func=cmd_domain_hypothesis)

    s = sub.add_parser("ownership", help="which module owns a question, and "
                       "what it is NOT for")
    s.add_argument("question", nargs="*", help="the question, in plain language")
    s.add_argument("--module", help="the entries one module owns")
    s.add_argument("--check", action="store_true",
                   help="verify the declaration against the code")
    s.set_defaults(func=cmd_ownership)

    s = sub.add_parser("status", help="generated pipeline status "
                       "(the perishable half of CLAUDE.md, computed)")
    s.add_argument("--write", action="store_true",
                   help="write STATUS.md instead of printing")
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("metrics", help="what moved since the last comparable "
                       "run (quiet when nothing did)")
    s.add_argument("--tool", default=None, help="only this tool's series")
    s.add_argument("--verbose", action="store_true",
                   help="print every value, not only the ones that moved")
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser("sql", help="run DuckDB over the store")
    s.add_argument("query", nargs="?"); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_sql)

    s = sub.add_parser("dashboard", help="display or stream the interactive tactical coaching dashboard")
    s.add_argument("--open", action="store_true", help="open dashboard in default web browser")
    s.add_argument("--serve", action="store_true", help="stream dashboard and video clips via local HTTP range server")
    s.add_argument("--port", type=int, default=8765, help="port to listen on with --serve (default: 8765)")
    s.add_argument("--videos-dir", default=r"C:\Users\grant\Videos", help="directory containing match MP4 videos")
    s.set_defaults(func=cmd_dashboard)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
