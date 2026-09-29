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
    reticle verify  --tier fast               known answers on a few sessions, no decode
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
from types import SimpleNamespace

import numpy as np

from .decode import sample_frames, sample_multi, sample_spans
from .checks import KNOWN_KD, check_hud, player_events, track_entries
from .rounds import build_rounds, summarise
from .scoreboard import ScoreboardReader, load_agent_icons, read_scoreboard, strip_rect
from . import cone, geometry, lighting
from .fidelity import FROZEN_WINDOWS
from .fingerprint import fingerprint
from .killfeed import (KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION,
                       KILLFEED_WEAPON_VERSION, KillfeedPortraitReader,
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
from .version import (ALLY_ICON_VERSION, COMBAT_REPORT_VERSION, MINIMAP_DARK_VERSION, SMOKE_VERSION, EXTRACTOR_VERSION, HUD_VERSION, MINIMAP_VERSION, PING_VERSION,
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
        self.cv_threads = 1        # small crops: see `passes._feed`
        self.hz = args.minimap_hz
        self.spans = spans         # the minimap has nothing to say off-round
        # Its table's metadata records a clip to a round cache (`spans_clip`).
        self.records_clip = True
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


def _roi_cache_stale(store, manifest, profile, name, hz=None, spans=None, gate=None) -> bool:
    """Whether set `name`'s stored cache differs from the one asked for: its
    rate, its spans, or its gate (`roi_cache.scoreboard_gate`)."""
    from .roi_cache import RoiCache
    cache = RoiCache.load(store.root, manifest, profile, name)[0]
    if cache is None:
        return True
    want = None if spans is None else [[float(a), float(b)] for a, b in spans]
    gate = None if gate is None else json.loads(json.dumps(gate))
    return ((hz is not None and float(cache.record["hz"]) != float(hz))
            or cache.record.get("spans") != want or cache.record.get("gate") != gate)


def _scoreboard_cache_gate(store, sid, args) -> dict:
    """The gate a scoreboard crop cache is written under, from the stored
    strip rows (`roi_cache.scoreboard_gate`); refuses a request the set
    cannot hold. The crops ride the scoreboard reader's own frames: the
    whole capture at `--hz`."""
    from .roi_cache import scoreboard_gate
    if args.cache_live:
        raise SystemExit("--cache-roi scoreboard rides the scoreboard reader over the whole "
                         "capture; it takes no --cache-live")
    if args.cache_hz is not None and float(args.cache_hz) != float(args.hz):
        raise SystemExit("--cache-roi scoreboard stores the scoreboard reader's frames, at "
                         "--hz; it takes no other --cache-hz")
    gate, why = scoreboard_gate(store.read_events("scoreboard_strip", sid))
    if gate is None:
        raise SystemExit(f"--cache-roi scoreboard gates on the strip witness: {why}; "
                         f"run `reticle strip {sid}` first")
    return gate


#: How long before each barrier drop a live-round cache starts: the last
#: buy-phase second shows the starting positions and everything placed in the
#: buy phase [domain:rounds/buy-phase-barriers].
LIVE_LEAD_MS = 1000.0
#: After the last round, the post-round period a live-round cache keeps.
LAST_POST_ROUND_MS = 10000.0


def _live_round_spans(store, sid, date) -> list[tuple[float, float]]:
    """Each round from just before its barrier drop to the next round's start,
    as `gametime` schedules them: the post-round period stays, since kills are
    legal in it [domain:rounds/post-round-period]."""
    from . import stalls
    rs = store.read_rounds(sid, date)
    hud = store.read_hud(sid, date)
    if rs is None or hud is None:
        raise SystemExit(f"--cache-live needs stored rounds and HUD for {sid}; "
                         f"run `reticle scan {sid}` first")
    gt = gametime.build_session_gametime(sid, hud, rs.to_pylist(),
                                         stall_list=stalls.for_session(store, sid, date))
    sch = gt.schedules
    return [(max(s.t_start_ms, s.t_live_ms - LIVE_LEAD_MS),
             max(s.t_end_ms, sch[i + 1].t_start_ms if i + 1 < len(sch)
                 else s.t_end_ms + LAST_POST_ROUND_MS))
            for i, s in enumerate(sch)]


def cmd_usage(args) -> int:
    """Show scan cost records, completed and failed, with source and reader time."""
    from .usage import load, format_usage

    store = Store(args.store)
    rows = load(store.root, args.session)
    if not rows:
        print("no scan usage records")
        return 0
    for row in rows[-args.limit:]:
        print(json.dumps(row, indent=2) if args.json else format_usage(row))
    return 0


def _parse_shards(specs) -> dict[str, int]:
    """`--shard NAME=N` values as a map; N below 2 is no shard."""
    out = {}
    for spec in specs or ():
        name, _, k = spec.partition("=")
        if not name or not k.isdigit() or int(k) < 1:
            raise SystemExit(f"--shard takes NAME=N with N a positive count, not {spec!r}")
        out[name] = int(k)
    return {name: k for name, k in out.items() if k > 1}


def _scan_pass(ctx, readers, cache, progress, usage, pipeline, workers, shards, cv_threads):
    """One pass over the chosen source: `(frames, None)` serial, `(frames, StagedRun)` staged.

    The serial path is `passes.run` or `run_cached`, untouched; `cv_threads`
    sets OpenCV's process-wide count around it and `_feed`'s per-reader
    toggles still apply. The staged path is `pipeline.run_staged`.
    """
    import cv2

    if pipeline == "serial":
        before = cv2.getNumThreads()
        if cv_threads is not None:
            cv2.setNumThreads(cv_threads)
        usage.cv_threads = {"pass": cv2.getNumThreads(),
                            "toggled": sorted(r.name for r in readers
                                              if getattr(r, "cv_threads", None) is not None)}
        try:
            if cache is not None:
                from .passes import run_cached
                return run_cached(ctx, readers, cache, progress, usage=usage), None
            return passes_run(ctx, readers, progress, usage=usage), None
        finally:
            if cv_threads is not None:
                cv2.setNumThreads(before)
    from .pipeline import run_staged
    got = run_staged(ctx, readers, cache, workers=1 if workers is None else workers,
                     shards=shards, usage=usage, progress=progress, cv_threads=cv_threads)
    usage.staged_run(got)
    return got.frames, got


def _publish_staged(out, publish, usage, session_id: str) -> dict:
    """Publish a scan's streams into `out` whole or not at all; the run record.

    `publish(staged)` writes every stream into a scratch store under
    `out/staging/<run_id>/`, and `Store.commit_staged` moves them into
    `out` together, with the usage record's `run_id` as the run's. A
    publish that stops part way -- a reader with zero rows exits after
    another has written -- leaves `out` as it was, and the usage record is
    written as `failed` with the reason before the exit goes on. A commit
    that fails is recorded the same way (see `Store.commit_staged`).
    """
    def failed(stage, exc):
        usage.status, usage.error = "failed", f"{stage}: {exc}"
        try:
            usage.write(out.root)
        except OSError as err:
            print(f"usage log could not be written: {err}", file=sys.stderr)

    staged = out.staging(usage.run_id)
    try:
        publish(staged)
    except BaseException as exc:
        out.discard_staged(staged)
        failed("publish", exc)
        raise
    try:
        return out.commit_staged(staged, usage.run_id, session_id)
    except BaseException as exc:
        failed("commit", exc)
        raise


def _scan_check(scan_once, sid, args, shards) -> int:
    """Run the requested path and the serial one into two temporary stores.

    Path a is the serial pass; path b is the pass the flags ask for. Against
    a staged path b, path a runs at b's `--cv-threads`, so the two paths
    differ in staging alone and the timings compare like with like. Without
    the flag path a keeps OpenCV's own pool while a threaded path b runs at
    `pipeline.STAGED_CV_THREADS`, so a timing check names the count. Against
    a serial path b at a count, path a is the serial pass on the pool, so
    the check compares the count with the pool rather than a pass with
    itself. Path b runs first, so its threads meet the lazily filled module
    caches (`killfeed._ME_CACHE`, `ally_portrait._REG`) cold rather than
    filled by the serial pass. Both read the store's manifest,
    crop cache and inputs and write only under the check directory, which is
    kept so each path's usage record stays readable. Every written file is
    compared byte for byte; where Parquet bytes differ the rows are compared
    too, to say where the tables part. Exits non-zero unless every file is
    byte-equal.
    """
    import tempfile
    from .pipeline import compare_trees

    root = (Path(args.check_dir) if args.check_dir
            else Path(tempfile.mkdtemp(prefix=f"reticle-check-{sid}-")))
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"--check-dir {root} is not empty")
    b_label = (f"{args.pipeline}, workers {1 if args.workers is None else args.workers}"
               if args.pipeline == "staged" else "serial")
    b_label += (f", shards {shards}" if shards else "")
    b_label += (f", OpenCV threads {args.cv_threads}" if args.cv_threads is not None else "")
    print(f"check      b: {b_label} -> {root / 'b'}")
    ub = scan_once(Store(root / "b"), args.pipeline, args.workers, shards, args.cv_threads)
    a_threads = args.cv_threads if args.pipeline == "staged" else None
    a_label = "serial" + (f", OpenCV threads {a_threads}" if a_threads is not None else "")
    print(f"check      a: {a_label} -> {root / 'a'}")
    ua = scan_once(Store(root / "a"), cv_threads=a_threads)
    if ua is None or ub is None:
        failed = " and ".join(n for n, u in (("a", ua), ("b", ub)) if u is None)
        print(f"check      path {failed} failed; nothing to compare")
        return 1
    entries = compare_trees(root / "a", root / "b")
    print(f"check      a = {a_label}, b = {b_label}")
    for e in entries:
        print(f"{e['verdict']:<10} {e['path']}  {e['detail']}")
    rows = [e for e in entries if e["rows_differ"]]
    equal = sum(e["verdict"] == "equal" for e in entries)
    print(f"check      {len(entries)} files, {equal} equal, "
          f"{len(rows)} with row differences; usage a {ua.run_id}, b {ub.run_id} "
          f"(under {root})")
    return 1 if equal < len(entries) or not entries else 0


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
    until = getattr(args, "until", None)
    if until is not None:
        if not (args.check and args.check_dir):
            raise SystemExit(
                "--until needs --check and --check-dir: a prefix scan's streams hold only "
                "the frames before the limit, and published into the store they would read "
                "as whole-capture streams; --check writes them into two scratch stores "
                "under the directory you name")
        if not 0 < until < float("inf"):
            raise SystemExit("--until takes a positive number of seconds")
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
    shards = _parse_shards(args.shard)
    if args.pipeline == "serial" and (shards or args.workers is not None):
        raise SystemExit("--workers and --shard need --pipeline staged")
    if args.check:
        import cv2
        if args.cache_roi:
            raise SystemExit("--check writes nothing into the store, and --cache-roi "
                             "writes crops there")
        if args.pipeline == "serial" and args.cv_threads in (None, cv2.getNumThreads()):
            raise SystemExit("--check compares the serial pass with the pass the flags ask "
                             "for, and these flags ask for the serial pass again; name "
                             "--pipeline staged or another --cv-threads")
        # The check re-reads every requested stream, current or not.
        args.force = True
    channels = set(args.only or ('hud', 'minimap', 'ping', 'roster', 'scoreboard',
                                 'ally_icon', 'minimap_dark', 'combat_report'))
    # IDENTITY RIDES EVERY SCAN. The top bar is drawn on every frame, so naming
    # the ten agents costs no decode of its own -- it joins the pass at 0.1 Hz.
    # A scan narrowed with `--only` is testing one specific thing and is left
    # alone; anything else reads the lineup unless `--no-lineup` says not to.
    want_lineup = args.lineup and not args.only
    spans = (_active_spans(store, sid, date)
             if channels & {'minimap', 'ping', 'ally_icon', 'minimap_dark'} else [])
    fps = float(src["fps"])

    want_hud = 'hud' in channels and (args.force or not store.has_hud(sid, date))
    # One reader writes the three killfeed streams from the views it already
    # has, so any stream going stale reruns it.
    want_portraits = ('hud' in channels and
                      (args.force
                       or store.events_version("killfeed_portrait", sid) != KILLFEED_PORTRAIT_VERSION
                       or store.events_version("killfeed_weapon", sid) != KILLFEED_WEAPON_VERSION
                       or store.events_version("killfeed_name", sid) != KILLFEED_NAME_VERSION))
    want_mm = 'minimap' in channels and (args.force or not store.has_minimap(sid, date))
    # Pings are events rather than a versioned table, but the cache key is the
    # VERSION, not the file's existence. Keying on existence made `PING_VERSION`
    # a stamp nothing read: bumping it re-read nothing, and a store could hold
    # pings at three definitions with no way to say which sessions were stale --
    # which is the one job version.py says a stamp exists to do.
    want_ping = 'ping' in channels and args.ping and (args.force
                               or store.events_version("ping", sid) != PING_VERSION)
    want_roster = 'roster' in channels and args.roster and (args.force or not store.has_roster(sid, date))
    # Rides the minimap's active spans at `--ally-hz` (`ALLY_DESCRIPTOR_HZ`);
    # versioned by its own stamp, so a descriptor change re-reads descriptors
    # and leaves positions alone.
    want_ally = 'ally_icon' in channels and (
        args.force or store.events_version("ally_icon", sid) != ALLY_ICON_VERSION)
    # Grey dark floor at 4 Hz over active spans: the smoke observation.
    # Versioned by its own stamp, so `reticle smokes` can re-adjudicate
    # without a re-read.
    want_dark = 'minimap_dark' in channels and (
        args.force or store.events_version("minimap_dark", sid) != MINIMAP_DARK_VERSION)
    # The combat report over the whole capture at 1 Hz: a header correlation
    # per frame, rows only where a panel may be up.
    want_report = 'combat_report' in channels and (
        args.force or store.events_version("combat_report", sid) != COMBAT_REPORT_VERSION)
    want_scoreboard = ('scoreboard' in channels and args.scoreboard and
                       (args.force or store.events_version("scoreboard", sid)
                        != SCOREBOARD_VERSION))
    # Lossless crops of a fixed ROI, so a reader change can rerun without a
    # decode (`reticle trial --from cache`). Opt-in: it rides the HUD rate, so
    # its crops sit on the HUD timeline's timestamps.
    # The scoreboard set keeps the scoreboard reader's frames inside the
    # strip gate (`roi_cache.scoreboard_gate`), so it rides at --hz.
    cache_gate = (_scoreboard_cache_gate(store, sid, args)
                  if args.cache_roi == "scoreboard" else None)
    cache_hz = args.cache_hz or args.hz
    cache_spans = _live_round_spans(store, sid, date) if args.cache_live else None
    want_cache = bool(args.cache_roi) and (args.force or _roi_cache_stale(
        store, manifest, profile, args.cache_roi, cache_hz, cache_spans, cache_gate))
    if args.only == ["roi_cache"] and not args.cache_roi:
        raise SystemExit("--only roi_cache needs --cache-roi <roi>")
    if (args.check and (want_hud or want_portraits) and killfeed_roi(profile) is not None
            and store.read_kf_mask(sid) is None):
        raise SystemExit("--check: no stored killfeed mask, and the HUD readers would "
                         "decode the capture to measure one")
    if not (want_hud or want_portraits or want_mm or want_ping or want_roster
            or want_scoreboard or want_ally or want_dark or want_report or want_cache):
        print(f"cache hit  session {sid}: requested channels are current or disabled; "
              "--force to re-read")
        return 0

    print(f"session    {sid}  ({src['filename']})")
    print(f"profile    {profile.name}")
    print(f"stages     " + ", ".join(
        ([f"hud {args.hz:g} Hz, whole capture"] if want_hud else [])
        + ([f"killfeed portraits, weapons and names {args.hz:g} Hz, whole capture"]
           if want_portraits else [])
        + ([f"minimap {args.minimap_hz:g} Hz, {len(spans)} active spans "
            f"({sum(b - a for a, b in spans) / 1000.0:.0f}s)"] if want_mm else [])
        + ([f"ping {args.ping_hz:g} Hz, active spans"] if want_ping else [])
        + ([f"roster {args.hz:g} Hz, whole capture"] if want_roster else [])
        + ([f"scoreboard {args.hz:g} Hz, whole capture"] if want_scoreboard else [])
        + ([f"ally icons {args.ally_hz:g} Hz, active spans"] if want_ally else [])
        + ([f"minimap dark {args.dark_hz:g} Hz, active spans"] if want_dark else [])
        + ([f"combat report {args.report_hz:g} Hz, whole capture"] if want_report else [])))

    def build_readers():
        """The pass's readers, built from the store's inputs; the prints are theirs."""
        hp = _HudPass(store, manifest, profile, args) if want_hud else None
        mp = _MinimapPass(store, manifest, profile, spans, args) if want_mm else None
        if mp is not None:
            # It reads `frame[box]` alone, so a minimap cache at its rate feeds
            # it; `--from cache` clips its spans to the cached rounds.
            from .roi_cache import declare_set
            declare_set(mp, "minimap", profile, (mp.w, mp.h))

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

        lp = (LineupReader(profile, ctx.wh, store.root, name=f"lineup:{sid}", session=sid)
              if want_lineup else None)
        ap = None
        if want_ally:
            from .minimap import ally_icon_reader
            ap = ally_icon_reader(ctx, hz=args.ally_hz, spans=spans,
                                  floor=mp.floor if mp is not None else None,
                                  slab=mp.slab if mp is not None else None)
            from .roi_cache import declare_set
            declare_set(ap, "minimap", profile, ctx.wh)
        dp = None
        if want_dark:
            from .minimap_dark import DarkRegionReader
            geo = geometry.path_of(sid, store.root)
            with np.load(geo) as z:
                dark_ref = lighting.reference(z)
            if dark_ref is None:
                print("minimap dark skipped: geometry has no lighting reference")
            else:
                dp = DarkRegionReader(
                    floor=mp.floor if mp is not None else ctx.floor(),
                    sgray=mp.sgray if mp is not None else ctx.sgray(),
                    static=ctx.map_reference(), ref=dark_ref,
                    box=minimap_roi_px(profile, *ctx.wh), hz=args.dark_hz, spans=spans)
                from .roi_cache import declare_set
                # It reads `frame[box]` alone, so the minimap cache feeds it on
                # its own grid (`cache_resample`).
                declare_set(dp, "minimap", profile, ctx.wh)
        cp = None
        if want_report:
            from .combat_report import CombatReportReader
            cp = CombatReportReader(Templates.load(profile.name), hz=args.report_hz, spans=None)
        xp = None
        if want_cache:
            from .roi_cache import RoiCacheWriter
            try:
                xp = RoiCacheWriter(store.root, manifest, profile, args.cache_roi, hz=cache_hz,
                                    spans=cache_spans, gate=cache_gate)
            except ValueError as exc:
                raise SystemExit(f"--cache-roi {args.cache_roi}: {exc}")
        readers = [r for r in (hp, kp, mp, pp, rp, sp, lp, ap, dp, cp, xp) if r is not None]
        return SimpleNamespace(hp=hp, kp=kp, mp=mp, pp=pp, rp=rp, sp=sp, lp=lp, ap=ap,
                               dp=dp, cp=cp, xp=xp, ctx=ctx, readers=readers)

    def live_rounds():
        try:
            return _live_round_spans(store, sid, date), None
        except SystemExit as exc:
            return None, str(exc)

    def choose_source(readers):
        # A pass whose readers all stay inside a cached ROI set is fed from the
        # crop cache: the same pixels, no decode. A cache written over rounds
        # holds no frames outside them: `--from cache` reads a span reader's
        # rounds only, `--from auto` does so where the cache holds every live
        # round of its spans and decodes otherwise, and each says which.
        from .roi_cache import choose_source as choose
        cache, why, notes = choose(store.root, manifest, profile, readers,
                                   args.frames_from, live_rounds)
        for line in notes:
            print(line)
        if cache is None and args.frames_from == "cache":
            raise SystemExit(f"--from cache: {why}")
        # A clipped stream must say which spans it left unread; one that
        # cannot would store unread time as time with nothing in it.
        mute = [r.name for r in readers if getattr(r, "spans_clip", None) is not None
                and not getattr(r, "records_clip", False)]
        if mute:
            raise SystemExit(f"--from {args.frames_from}: {', '.join(mute)} would read the "
                             f"cache's rounds only, and its stream cannot record the spans "
                             f"it skips; use --from video")
        print(f"frames     {args.frames_from}: "
              f"{'from ' + why if cache is not None else 'decoded (' + why + ')'}")
        if until is not None:
            # After `cache_for`: a span on a whole-capture reader would make
            # it refuse a whole-capture cache.
            from .pipeline import limit_to_prefix
            cache = limit_to_prefix(readers, until * 1000.0, cache)
            print(f"prefix     only frames observed before {until:g} s")
        return cache, why

    def publish(out, R, n_dec, dt):
        """Write the readers' streams into `out`, a staging store that
        `_publish_staged` commits whole; inputs still come from `store`, so
        each path printed below is the stream's place in staging."""
        hp, kp, mp, pp, rp, sp, lp, ap, dp, cp, xp = (
            R.hp, R.kp, R.mp, R.pp, R.rp, R.sp, R.lp, R.ap, R.dp, R.cp, R.xp)
        if hp is not None:
            if not hp.rows:
                raise SystemExit("decoded zero frames -- is the file readable?")
            path = out.write_hud(hp.rows, _FP(src, sid), profile.name, date)
            ev = player_events(
                [r["t_ms"] for r in hp.rows],
                [r["kf_kill_mask"] for r in hp.rows],
                [r["kf_death_mask"] for r in hp.rows],
                [r["kf_kill_wx"] for r in hp.rows],
                [r["kf_death_wx"] for r in hp.rows],
            )
            print(f"HUD        {len(hp.rows)} rows -> {path}")
            print(f"           tracked entries: {ev['kills']} kills, {ev['deaths']} deaths")
        if kp is not None:
            events = kp.events(sid)
            path = out.write_events("killfeed_portrait", sid, events)
            print(f"portraits  {len(events) - 1} observations -> {path}")
            weapons = kp.weapon_events(sid)
            path = out.write_events("killfeed_weapon", sid, weapons)
            print(f"weapons    {len(weapons) - 1} observations -> {path}")
            names = kp.name_events(sid)
            path = out.write_events("killfeed_name", sid, names)
            print(f"names      {len(names) - 1} observations -> {path}")
        if mp is not None:
            if not mp.rows:
                raise SystemExit("decoded zero frames inside active spans "
                                 "-- is segmentation right?")
            frames_from = getattr(mp, "frames_from", "video")
            path = out.write_minimap(
                mp.rows, _FP(src, sid), profile.name, date,
                frames_from=None if frames_from.startswith("video") else frames_from,
                spans_clip=getattr(mp, "spans_clip", None))
            got = sum(1 for r in mp.rows if r["self_x"] is not None)
            print(f"minimap    {len(mp.rows)} rows -> {path}")
            print(f"           widget absent {mp.n_absent}/{len(mp.rows)} "
                  f"({mp.n_absent / len(mp.rows) * 100:.1f}%)")
            print(f"           self raw {got}/{len(mp.rows)} "
                  f"({got / len(mp.rows) * 100:.1f}%)")
        if ap is not None:
            from .adjudication.minimap_candidates import (
                MINIMAP_ICON_DECISION_VERSION, accepted, ally_decisions)
            candidate_revision = out.write_candidates("ally_icon", sid,
                                                      ap.candidate_rows(sid), ap.frames)
            batch = out.read_candidate_batch("ally_icon", sid, candidate_revision)
            candidates = batch["rows"]
            # The batch was just read and verified against its revision; the
            # decision write and read validate against those rows.
            out.write_decisions("ally_icon", sid, candidate_revision,
                                MINIMAP_ICON_DECISION_VERSION,
                                ally_decisions(candidates), candidates=candidates)
            decisions = out.read_decisions("ally_icon", sid, candidate_revision,
                                           MINIMAP_ICON_DECISION_VERSION,
                                           candidates=candidates)
            kept = accepted(candidates, decisions)
            # Check the previous output contract before publishing the replay.
            ap.events(sid, kept, candidate_revision)
            events = AllyIconReader.replay_events(
                sid, batch["frames"], kept, ap.hz, candidate_revision,
                frames_from=ap.frames_from, spans_clip=getattr(ap, "spans_clip", None))
            path = out.write_events("ally_icon", sid, events)
            cov = events[0]
            print(f"ally icons {cov['frames']} frames, {cov['icons']} icons, "
                  f"{cov['described']} described -> {path}")
            print(f"           refused {cov['refused_reasons']}")
        if lp is not None:
            import json
            result = lp.finish()[0]
            out_path = out.root / "lineups" / f"{sid}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({**result, "session": sid}, indent=2),
                                encoding="utf-8")
            named = {side: [r["agent"] for r in rows if r["agent"]]
                     for side, rows in result["sides"].items()}
            print(f"lineup     {result['frames']} frames -> {out_path}")
            for side in ("ally", "enemy"):
                got = named[side]
                print(f"           {side} {len(got)}/5 named"
                      + (f": {', '.join(got)}" if got else
                         " -- no slot separated from its runner-up"))
        if rp is not None:
            if not rp.rows:
                raise SystemExit("decoded zero frames -- is the file readable?")
            path = out.write_roster(rp.rows, _FP(src, sid), profile.name, date)
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
            print(f"roster     {n} rows -> {path}")
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

        if cp is not None:
            rows = cp.events(sid)
            path = out.write_events("combat_report", sid, rows)
            print(f"combat report {rows[0]['frames']} frames, rows read in {rows[0]['rows_read']} -> {path}")

        if xp is not None:
            print(f"roi cache  {len(xp._index)} {args.cache_roi} crops, "
                  f"{xp._offset / 2**20:.0f} MB -> {xp.paths[0].parent}")
            if xp.gate is not None:
                print(f"           {xp.gate['witness']} gate kept {len(xp._index)} of "
                      f"{xp.frames_offered} frames offered ({xp.gate['samples']} "
                      f"stored samples in its {len(xp.gate['spans'])} spans)")

        if dp is not None:
            rows = dp.events(sid, geometry.key_of(sid, store.root))
            path = out.write_events("minimap_dark", sid, rows)
            print(f"minimap dark {rows[0]['frames']} frames, {rows[0]['unobserved']} unobserved -> {path}")

        if pp is not None:
            pp.finish()
            path = out.write_events("ping", sid, pp.events(sid))
            by: dict[str, int] = {}
            for kind, *_r in pp.hits:
                by[kind] = by.get(kind, 0) + 1
            print(f"ping       {len(pp.hits)} confirmed -> {path}")
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
            events = sp.events(sid)
            path = out.write_events("scoreboard", sid, events)
            accepted = sum(r["credits"] is not None for r in sp.rows)
            candidates = sum(r["credits_candidate"] is not None for r in sp.rows)
            print(f"scoreboard {sp.frames_open}/{sp.frames_offered} frames open, "
                  f"{accepted}/{candidates} credit candidates gated -> {path}")
            print(f"           closed by {events[0]['closed_reasons']}")
        print(f"one pass   {n_dec} frames retrieved in {dt:.1f}s")

    def scan_once(out, pipeline="serial", workers=None, shards=None, cv_threads=None):
        """Build, choose the source, run one pass and publish into `out`.

        Returns the usage record, or None when a staged pass failed; the failed
        record is written with its reason and nothing is published."""
        setup_t0 = time.perf_counter_ns()
        R = build_readers()
        t0 = time.perf_counter()
        last = [t0]

        def progress(n, smp):
            now = time.perf_counter()
            if now - last[0] >= 2.0:
                pct = (smp.t_ms / src["duration_ms"] * 100) if src["duration_ms"] else 0.0
                sys.stdout.write(f"\r{n:>7d} frames  {_fmt_hms(smp.t_ms)}  {pct:5.1f}%")
                sys.stdout.flush()
                last[0] = now

        cache, why = choose_source(R.readers)
        if cache is None:
            _normalise_decoded(R, manifest, store)
        from .usage import ScanUsage
        usage = ScanUsage(manifest, profile.name, R.readers,
                          f"cache:{cache.record['version']}" if cache is not None else "video")
        usage.setup_ns = time.perf_counter_ns() - setup_t0
        usage.pipeline, usage.workers, usage.shards = pipeline, workers, dict(shards or {})
        usage.until_s = until
        with usage.timed_pass():
            n_dec, staged = _scan_pass(R.ctx, R.readers, cache, progress, usage, pipeline,
                                       workers, shards, cv_threads)
        publish_t0 = time.perf_counter_ns()
        sys.stdout.write("\r" + " " * 72 + "\r")
        dt = time.perf_counter() - t0
        if staged is not None and staged.status != "completed":
            print(f"pass failed  {staged.error}; nothing published", file=sys.stderr)
            try:
                usage.write(out.root)
            except OSError as exc:
                print(f"usage log could not be written: {exc}", file=sys.stderr)
            return None
        run = _publish_staged(out, lambda staged: publish(staged, R, n_dec, dt), usage, sid)
        usage.publish_ns = time.perf_counter_ns() - publish_t0
        print(f"published  run {run['run_id']}: {len(run['files'])} files moved from staging "
              f"into {out.root}" + (f", {len(run['kept'])} equal revisions kept"
                                   if run["kept"] else ""))
        try:
            usage.write(out.root)
            usage.write_metric(out.root)
        except OSError as exc:
            print(f"usage log could not be written: {exc}", file=sys.stderr)
        print(f"usage      run {usage.run_id} ({pipeline}"
              + (f", workers {workers}" if workers is not None else "")
              + (f", shards {shards}" if shards else "") + ")")
        return usage

    if args.check:
        return _scan_check(scan_once, sid, args, shards)
    usage = scan_once(store, args.pipeline, args.workers, shards, args.cv_threads)
    if usage is None:
        return 1
    print(f"\nnext: reticle verify {sid}")
    return 0


def _normalise_decoded(R, manifest, store) -> None:
    """On a decode pass, feed the minimap readers a variant session's widget
    resampled into the baked frame (`widget_frame`); a cache pass is already
    normalised by `RoiCache.samples`. A placement the frame cannot hold is
    refused by name, never read as an absent widget."""
    from . import widget_frame as wf
    mine = {id(r) for r in (R.mp, R.pp, R.ap, R.dp) if r is not None}
    src = manifest["source"]
    frame = (wf.for_session(manifest, [0, 0, int(src["width"]), int(src["height"])], store.root)
             if mine else None)
    if frame is None:
        return
    if frame.refusal is not None:
        raise SystemExit(f"minimap refused: {wf.refusal_text(frame.refusal)}")
    R.readers[:] = [wf.Normalised(r, frame) if id(r) in mine else r for r in R.readers]
    print(f"widget     {len(frame.segments)} placements from the manifest "
          f"({wf.WIDGET_FRAME_VERSION}); minimap readers read the baked frame")


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

    `--tier fast` runs the fixed checks of `tiers.FAST` instead: known answers
    on a few sessions from storage and the crop cache, the default sanity
    check between the unit tests and a corpus run.
    """
    if getattr(args, "tier", None):
        return _verify_tier(args)
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


def _verify_tier(args) -> int:
    """Print each check of one verification tier; exit 1 unless all pass."""
    from . import tiers

    store = Store(args.store)
    t0 = time.perf_counter()
    print(f"tier {args.tier}: {len(tiers.TIERS[args.tier])} declared checks, storage and "
          f"crop cache only")
    for sid in dict.fromkeys(c.session for c in tiers.TIERS[args.tier]):
        print(f"  {sid}  {store.read_manifest(sid)['source']['path']}")
    print()
    results = tiers.run(store, args.tier, only=args.only)
    for r in results:
        print(f"{r['status']:<6} {r['id']}  [{r['kind']}]  {r['seconds']} s")
        print(f"       measured {r['measured']}   known {r['known']}")
        print(f"       source   {r['source']}")
        if r["detail"]:
            for line in str(r["detail"]).splitlines():
                print(f"       {line}")
    n = Counter(r["status"] for r in results)
    print()
    print(f"{n['PASS']} pass, {n['FAIL']} fail, {n['STALE']} stale of {len(results)} "
          f"in {time.perf_counter() - t0:.1f} s")
    return 0 if n["PASS"] == len(results) else 1


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
    icons = load_agent_icons(store.root)
    for smp in sample_frames(str(media), args.hz, src["fps"], args.max_frames):
        sb = read_scoreboard(smp.frame, templates,
                             args.min_confidence, args.min_margin,
                             strip_rect(profile.name, smp.frame.shape[1], smp.frame.shape[0]),
                             icons)
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


def cmd_strip(args) -> int:
    """The round-history strip at every cached frame, from the hud crop cache's
    centre crop (`scoreboard_strip`): a second witness that the Tab board is
    on screen. Decodes no video."""
    from . import scoreboard_strip as strip
    from .roi_cache import RoiCache

    store = Store(args.store)
    for sid in _sessions_arg(store, args):
        man = store.read_manifest(sid)
        src = man["source"]
        if (int(src["width"]), int(src["height"])) != strip.MEASURED_WH:
            print(f"{sid}: the strip is measured at 1920x1080 -- skipped")
            continue
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "hud")
        if cache is None:
            print(f"{sid}: no hud crop cache ({why}) -- skipped")
            continue
        rect = cache.rect_of(strip.ROI)
        reads = [(f, t, strip.read_strip(crop, rect)) for f, t, crop in cache.crops(strip.ROI)]
        rows = strip.strip_events(sid, reads, rect, cache.record["version"])
        out = store.write_events("scoreboard_strip", sid, rows)
        print(f"{sid}: {rows[0]['frames']} frames, {rows[0]['verdicts']} -> {out}")
    return 0


def _presence_counts(samples: list[dict], on=None) -> dict:
    """Open samples, holds, single-sample holds and one-sample holes under one
    reading of presence (`adjudication.scoreboard.presence_runs`)."""
    from .adjudication.scoreboard import presence_runs

    runs = presence_runs(samples, on)
    test = on or (lambda s: s["present"])
    return {"samples_open": sum(1 for s in samples if test(s)), "runs": len(runs),
            "runs_single_sample": sum(r["single"] for r in runs),
            "holes": sum(len(r["holes"]) for r in runs),
            "runs_with_hole": sum(1 for r in runs if r["holes"])}


def cmd_openings(args) -> int:
    """Scoreboard openings from storage, the slab test's rows and the strip's
    reconciled sample by sample (`adjudication.scoreboard`). Stores one
    `scoreboard_presence` row per sample, with what each witness said and the
    opening's verdict, and a coverage row counting holds, holes and
    disagreements under the slab test alone and combined. Decodes nothing."""
    from .adjudication.scoreboard import (SCOREBOARD_AGENT_VERSION, board_presence,
                                          presence_runs, scoreboard_openings)
    from .version import SCOREBOARD_STRIP_VERSION

    store = Store(args.store)
    for sid in _sessions_arg(store, args):
        board = store.read_events("scoreboard", sid)
        if not board:
            print(f"{sid}: no scoreboard rows -- skipped")
            continue
        strip = store.read_events("scoreboard_strip", sid)
        stored_strip = strip[0].get("scoreboard_strip_version") if strip else None
        if stored_strip != SCOREBOARD_STRIP_VERSION:
            print(f"{sid}: strip rows {'absent' if stored_strip is None else 'at ' + stored_strip}, "
                  f"current is {SCOREBOARD_STRIP_VERSION} -- run `reticle strip {sid}`; skipped")
            continue
        presence = board_presence(board, strip)
        samples = presence["samples"]
        openings = scoreboard_openings(board, strip_rows=strip)
        by_frame = {int(o["frame_idx"]): o for o in openings}
        hold = {}
        for k, run in enumerate(presence_runs(samples)):
            for s in samples[run["a"]:run["z"] + 1]:
                hold[s["frame_idx"]] = k
        common = {"session_id": sid, "scoreboard_presence_version": SCOREBOARD_AGENT_VERSION,
                  "scoreboard_version": board[0].get("scoreboard_version"),
                  "scoreboard_strip_version": stored_strip, "source": "scoreboard_presence"}
        rows = []
        for s in samples:
            o = by_frame.get(s["frame_idx"])
            rows.append({**common, "kind": "sample", **s, "hold": hold.get(s["frame_idx"]),
                         "opening_accepted": None if o is None else o["accepted"],
                         "opening_reason": None if o is None else o["reason"],
                         "opening_enemy_rows_from": None if o is None else o["enemy_rows_from"]})
        witness = Counter(s["witness"] for s in samples)
        unreadable = Counter(s["slab"] for s in samples if s["witness"] == "unreadable")
        closed = Counter(s["slab_reason"] for s in samples if s["slab"] == "closed")
        coverage = {**common, "kind": "coverage", "samples": len(samples),
                    "slab_closed_from": presence["slab_closed_from"],
                    "slab": _presence_counts(samples, lambda s: s["slab"] == "open"),
                    "combined": _presence_counts(samples),
                    "witness": dict(sorted(witness.items())),
                    "unreadable_slab_open": unreadable.get("open", 0),
                    "unreadable_slab_closed": unreadable.get("closed", 0),
                    "slab_closed_reasons": {str(k): v for k, v in sorted(
                        closed.items(), key=lambda kv: str(kv[0]))},
                    "openings": len(openings),
                    "openings_accepted": sum(o["accepted"] for o in openings),
                    # accepted on the portrait scores that alone placed the
                    # enemy rows: they witness the agents, not the rows
                    "openings_accepted_enemy_rows_from_portraits": sum(
                        o["accepted"] and o["enemy_rows_from"] == "portraits" for o in openings),
                    "openings_strip_only": sum(o["reason"] == "strip_only_no_rows"
                                               for o in openings)}
        out = store.write_events("scoreboard_presence", sid, [coverage] + rows)
        a, b = coverage["slab"], coverage["combined"]
        print(f"{sid}: open {a['samples_open']} -> {b['samples_open']}, holds {a['runs']} -> "
              f"{b['runs']}, single {a['runs_single_sample']} -> {b['runs_single_sample']}, "
              f"holes {a['holes']} -> {b['holes']}; accepted {coverage['openings_accepted']} "
              f"({coverage['openings_accepted_enemy_rows_from_portraits']} with enemy rows from "
              f"the portraits alone); "
              f"slab_only {witness.get('slab_only', 0)}, strip_only {witness.get('strip_only', 0)}, "
              f"unreadable {witness.get('unreadable', 0)} -> {out}")
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
        from .team_vision import load_inputs
        inputs, why = load_inputs(args.store, sid, profile, w, h)
        if inputs is None:
            print("minimap    no baked geometry -- tag the session map or run "
                  "minimap_geometry.py for its (map, profile) key")
        else:
            for note in inputs.notes:
                print(f"minimap    {note}")
            mm_box, mm_floor, mm_slab = inputs.box, inputs.floor, inputs.slab
            mm_sgray, mm_passable, mm_light = inputs.sgray, inputs.passable, inputs.light
            med = inputs.static

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
        producers = ("cli.py", "minimap.py", "track.py", "cone.py", "lighting.py", "minimap_lifecycle.py", "team_vision.py",
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
        # Second-life badge reads ride the killfeed portrait events; only a
        # current version carries them, so a stale store counts every death.
        from .adjudication.death import stored_second_life
        second_life = stored_second_life(store.read_events("killfeed_portrait", sid),
                                         KILLFEED_PORTRAIT_VERSION)
        rs = build_rounds(hud, second_life)
        if not rs:
            continue
        mp = next((t.split(":", 1)[1] for t in man.get("tags", []) if t.startswith("map:")), "?")
        for r in rs:
            r["map"] = mp
            r["session_id"] = sid
        every += rs
        store.write_rounds(rs, sid, date, KILLFEED_PORTRAIT_VERSION if second_life is not None else None)
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
    # A new observation revision invalidates this derived association, and so
    # does a new identity rule or reference table: segments carry their names.
    from .adjudication.identity import AGENT_IDENTITY_VERSION, load_ally_portrait_references

    table = load_ally_portrait_references(store.root) or {}
    refs_version = table.get("version")
    if table.get("teammate_fit"):
        refs_version = f"{refs_version}+{table['teammate_fit'].get('version')}"
    # The lineup names from the stored lineup and the scoreboard's side sets,
    # and deaths bind to pieces: a rescan of either changes the entities
    # without touching the ally icons, so their bytes are stamped too.
    inputs = hashlib.sha256()
    for part in (store.root / "lineups" / f"{sid}.json",
                 store.events_path("scoreboard", sid), store.events_path("death", sid)):
        inputs.update(part.read_bytes() if part.is_file() else b"-")
    inputs_revision = inputs.hexdigest()
    path = store.events_path("round_entity", sid)
    stamped = None
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            first = json.loads(f.readline() or "{}")
        stamped = (first.get("round_entity_version"), first.get("round_lifetime_version"),
                   first.get("ally_icon_revision"), first.get("agent_identity_version"),
                   first.get("ally_portrait_refs_version"), first.get("inputs_revision"))
    if stamped == (ROUND_ENTITY_VERSION, ROUND_LIFETIME_VERSION, source_revision,
                   AGENT_IDENTITY_VERSION, refs_version, inputs_revision) and not args.force:
        print(f"cache hit  session {sid} already has round entities at "
              f"{ROUND_ENTITY_VERSION} / {ROUND_LIFETIME_VERSION}; --force to recompute")
        return 0
    rounds = build_rounds(store.read_hud(sid, date))
    roster = None
    if store.has_roster(sid, date):
        t = store.read_roster(sid, date)
        roster = {"t_ms": t.column("t_ms").to_pylist(),
                  "alive_ally": t.column("alive_ally").to_pylist()}
    deaths = store.read_events("death", sid) if store.has_events("death", sid) else None
    box = minimap_roi_px(get_profile(manifest["source_profile"]),
                         int(manifest["source"]["width"]),
                         int(manifest["source"]["height"]))
    from .lineup import load_lineup
    from .adjudication.identity import load_ally_portrait_references, load_identity_gallery

    lineup = load_lineup(sid, store.root)
    references = load_ally_portrait_references(store.root) if lineup else None
    gallery = load_identity_gallery(store.root) if lineup else None
    from .menu import stored_menu
    menu, menu_stamp = stored_menu(store, sid)
    rows = session_lifetimes(sid, events, rounds, widget_scale(box[2] - box[0]),
                             roster, source_revision, deaths=deaths,
                             lineup=lineup, gallery=gallery, references=references,
                             menu=menu.at if menu is not None else None)
    rows[0]["menu_open"] = menu_stamp
    # Stamp the rules that named the segments, so a later change recomputes.
    rows[0]["agent_identity_version"] = AGENT_IDENTITY_VERSION
    rows[0]["ally_portrait_refs_version"] = refs_version
    rows[0]["inputs_revision"] = inputs_revision
    out = store.write_events("round_entity", sid, rows)
    cov = rows[0]
    ents = [r for r in rows if r["kind"] == "entity"]
    by_family = Counter(e["family"] for e in ents)
    print(f"session    {sid}  ally_icon at {events[0].get('hz')} Hz")
    print(f"rounds     {cov.get('rounds', 0)} associated, "
          f"{cov.get('frames', 0)} frames, {cov.get('absent_frames', 0)} widget-absent")
    print(f"entities   {len(ents)}  " + "  ".join(f"{k} {v}" for k, v in sorted(by_family.items())))
    if lineup:
        named_allies = sum(1 for e in ents if e["family"] == "ally" and e.get("agent"))
        total_allies = by_family.get("ally", 0)
        print(f"identity   {named_allies} of {total_allies} ally entities resolved "
              f"({named_allies / max(1, total_allies) * 100:.1f}%)")
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

    from .menu import stored_menu
    menu, _menu_stamp = stored_menu(store, sid)
    fixes = resolve(raw, step, scale,
                    absent_t=absent_instants(rows, menu.at if menu is not None else None),
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
        from .menu import stored_menu
        menu, _menu_stamp = stored_menu(store, sid)
        score, counts = audit_scoreline(hud), audit_roster_deltas(
            hud, roster, menu=menu.at if menu is not None else None)
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
        from .clipserve import RangeHandler, serve

        class DashboardHandler(RangeHandler):
            html_path = p
            videos_dir = Path(args.videos_dir)

        return serve(DashboardHandler, args.port, "dashboard", open_browser=args.open)

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


def cmd_vision(args) -> int:
    """Store the team's adjudicated vision per frame, from the minimap crop cache.

    Runs `team_vision.TeamVision` -- the chain `overlay` draws -- over every
    frame of the session's minimap `roi_cache`, in time order, and writes
    `events/team_vision/<session>.jsonl`. Decodes no capture: the four pixel
    stages (`widget_drawn`, `ally_icons`, `self_icons`, `lit_mask`) read the
    cached crops. A session with no cache or no geometry is reported and
    skipped, never guessed.

    `--at-candidates` computes only the frames around each ability candidate's
    instant (`team_vision.at`), after a warm-up of `--warmup-ms`; it writes
    only where no full product is stored, and says so in its coverage row.
    `--check` writes nothing: it compares what it computed with the stored
    product at the same frames, which is how a speed change or the on-demand
    form is shown to reproduce the full run.
    """
    import time
    from collections import Counter

    from . import lighting, stalls
    from .minimap_diagnostics import DIAGNOSTICS_VERSION
    from .minimap_lifecycle import LIFECYCLE_VERSION
    from .roi_cache import ROI_CACHE_VERSION, RoiCache
    from .team_vision import TeamVision, at, compare_rows, frame_row, load_inputs
    from .track import TRACK_VERSION
    from .version import TEAM_VISION_VERSION, TEARDROP_VERSION

    store = Store(args.store)
    targets = store.sessions() if args.all else [_resolve_session(store, args.session)]
    warmup_ms = args.warmup_ms
    instants = None
    if args.at_candidates:
        from .adjudication.ability import _components, _labels
        instants = {}
        for c in _components(store.root, _labels(store.root)):
            instants.setdefault(c["session_id"], set()).add(float(c["observed_t_ms"]))
    for manifest in targets:
        sid = manifest["session_id"]
        profile = get_profile(manifest["source_profile"])
        src = manifest["source"]
        w, h = int(src["width"]), int(src["height"])
        cache, why = RoiCache.load(store.root, manifest, profile, "minimap")
        if cache is None:
            print(f"{sid}: no minimap crop cache ({why}) -- skipped")
            continue
        inputs, why = load_inputs(store.root, sid, profile, w, h)
        if inputs is None:
            print(f"{sid}: {why} -- skipped")
            continue
        rx0, ry0, rx1, ry1 = cache.rect_of("minimap")
        x0, y0, x1, y1 = inputs.box
        if not (rx0 <= x0 and ry0 <= y0 and x1 <= rx1 and y1 <= ry1):
            print(f"{sid}: cache rect {cache.rect_of('minimap')} does not hold the widget "
                  f"box {list(inputs.box)} -- skipped")
            continue
        if instants is not None and not instants.get(sid):
            print(f"{sid}: no ability candidates -- skipped")
            continue
        stored = (store.read_events("team_vision", sid)
                  if store.events_path("team_vision", sid).is_file() else [])
        stored_mode = next((r.get("mode", "full") for r in stored
                            if r.get("kind") == "coverage"), None)
        if args.check and not stored:
            print(f"{sid}: no stored team_vision to check against -- skipped")
            continue
        inputs.stalls = stalls.for_session(store, sid, _date_of(manifest))
        common = {"session_id": sid, "team_vision_version": TEAM_VISION_VERSION}
        rows, widget = [], Counter()
        times = sorted({float(t) for t in cache.t_ms})
        started = time.perf_counter()
        if instants is not None:
            got = at(cache, inputs, sorted(instants[sid]), warmup_ms=warmup_ms,
                     distance_diagnostics=False)
        else:
            vision = TeamVision.from_inputs(inputs, distance_diagnostics=False)
            got = ((smp.frame_idx, vision.step(smp.frame[y0:y1, x0:x1], smp.t_ms))
                   for smp in cache.samples(times, rois=["minimap"]))
        for frame_idx, frame in got:
            widget[frame.widget] += 1
            rows.append({**common, **frame_row(frame, frame_idx)})
            if len(rows) % 500 == 0:
                sys.stdout.write(f"\r  {sid}  {len(rows)}/{len(times)} frames")
                sys.stdout.flush()
        sys.stdout.write("\r" + " " * 60 + "\r")
        elapsed = time.perf_counter() - started
        if args.check:
            cmp = compare_rows(rows, stored)
            differ = cmp.pop("differ_at_ms")
            print(f"{sid}: checked {cmp['frames']} computed frames against the stored "
                  f"{stored_mode} product in {elapsed:.0f} s: {cmp['missing']} missing, "
                  f"{cmp['rows_equal']} rows equal, {cmp['masks_equal']} masks equal, "
                  f"{cmp['icons_equal_but_ids']} icon lists equal less track ids"
                  + (f"; masks differ at {differ[:10]} ms" if differ else ""))
            continue
        if instants is not None and stored_mode == "full":
            print(f"{sid}: a full team_vision product is stored; the {len(rows)} on-demand "
                  f"frames ({elapsed:.0f} s) are not written over it -- use --check")
            continue
        coverage = {**common, "kind": "coverage", "frames": len(rows),
                    "cache_frames": len(times), "widget": dict(sorted(widget.items())),
                    "source": "roi_cache/minimap", "roi_cache_version": ROI_CACHE_VERSION,
                    "cache_hz": cache.record.get("hz"),
                    "geometry_key": inputs.geometry_key,
                    "lighting_version": (lighting.LIGHTING_VERSION
                                         if inputs.light is not None else None),
                    "track_version": TRACK_VERSION,
                    "teardrop_version": TEARDROP_VERSION,
                    "lifecycle_version": LIFECYCLE_VERSION,
                    "diagnostics_version": DIAGNOSTICS_VERSION,
                    "stall_version": stalls.STALL_VERSION,
                    "stalls_known": inputs.stalls is not None,
                    # `overlay`'s default: no origin-event file, so an
                    # appearance is eligible only at a boundary or by continuity.
                    "origin_events": 0,
                    "notes": inputs.notes}
        if instants is not None:
            # Track ids count from each warm-up's start; see `team_vision.at`.
            coverage.update(mode="at_instants", instants=len(instants[sid]),
                            warmup_ms=warmup_ms)
        rows.insert(0, coverage)
        out = store.write_events("team_vision", sid, rows)
        drawn = widget.get("drawn", 0)
        print(f"{sid}: {len(rows) - 1} frames, {drawn} drawn, "
              f"{widget.get('not_drawn', 0)} no widget, {widget.get('stale', 0)} stale "
              f"in {elapsed:.0f} s -> {out}")
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


def cmd_combat_report(args) -> int:
    """Panels, rounds and per-round counts from stored `combat_report` rows.
    Decodes no video."""
    from .adjudication.combat_report import events as report_events
    from .rounds import player_death_times

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid, date = manifest["session_id"], _date_of(manifest)
    rows = store.read_events("combat_report", sid)
    if not rows:
        raise SystemExit(f"{sid}: no combat_report rows -- run `reticle scan {sid} --only combat_report`")
    if rows[0].get("combat_report_version") != COMBAT_REPORT_VERSION:
        raise SystemExit(f"{sid}: combat_report rows are {rows[0].get('combat_report_version')}, "
                         f"current is {COMBAT_REPORT_VERSION} -- re-scan before trusting them")
    rounds = store.read_rounds(sid, date)
    if rounds is None:
        raise SystemExit(f"{sid}: no stored rounds -- run `reticle rounds {sid}` first")
    deaths = player_death_times(store.read_hud(sid, date))
    out_rows = report_events(sid, rows, rounds.to_pylist(), deaths)
    out = store.write_events("combat_report_round", sid, out_rows)
    head = out_rows[0]
    print(f"{sid}: {head['panels']} panels over {head['rounds_with_panel']}/{head['rounds']} rounds; "
          f"report kills {head['kills']}, deaths {head['deaths']}, assists {head['assists']}; "
          f"disagree with stored rounds on kills {head['kills_disagree']}, deaths {head['deaths_disagree']} -> {out}")
    print(f"verdict K/D {head['kills_verdict']}/{head['deaths_verdict']} "
          f"({head['verdict_from_killfeed']} rounds from the killfeed, the rest from the report)")
    for r in out_rows:
        if r["kind"] == "round" and (r["kills_agree"] is False or r["deaths_agree"] is False
                                     or r["kills"] is None):
            print(f"  round {r['round_no']:>2}: report K{r['kills']} D{r['deaths']}  "
                  f"stored K{r['stored_kills']} D{r['stored_deaths']}  {r['reason'] or ''}")
    _combat_report_identity(store, sid, date, rows, rounds.to_pylist(), deaths)
    return 0


def _combat_report_identity(store, sid, date, rows, rounds, death_times) -> None:
    """Name report rows through `adjudication.identity` from stored data."""
    from .adjudication import combat_report as adj
    from .adjudication.identity import identity_events, load_identity_gallery
    from .checks import track_entries
    from .lineup import load_lineup

    lineup = load_lineup(sid, store.root)
    if not lineup or not lineup.get("sides", {}).get("enemy"):
        print(f"  identity: no stored lineup for {sid}; rows stay unnamed")
        return
    frames = [r for r in rows if r.get("kind") == "frame"]
    ps = adj.panels(frames, death_times)
    adj.assign_rounds(ps, rounds)
    hud = store.read_hud(sid, date)
    t = hud.column("t_ms").to_pylist()
    tracks = lambda c: [x for x in track_entries(t, hud.column(f"kf_{c}_mask").to_pylist(),
                                                 hud.column(f"kf_{c}_wx").to_pylist())
                        if x["counted"]]
    portraits = [o for o in store.read_events("killfeed_portrait", sid)
                 if o.get("kind") == "portrait_observation"]
    board = [{"t": r["t_ms"], "agent": r.get("portrait_agent_best"),
              "kills": r.get("kills"), "deaths": r.get("deaths")}
             for r in store.read_events("scoreboard", sid)
             if r.get("kind") == "row_observation" and r.get("team") == "enemy"
             and r.get("portrait_agent_best")]
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    death_rows = store.read_events("death", sid)
    if death_rows and death_rows[0].get("death_adjudication_version") != DEATH_ADJUDICATION_VERSION:
        print(f"  deaths: stored at {death_rows[0].get('death_adjudication_version')}, current is "
              f"{DEATH_ADJUDICATION_VERSION}; rows stay unbound -- run `reticle deaths {sid}`")
        death_rows = []
    elif not death_rows:
        print(f"  deaths: none stored; rows stay unbound -- run `reticle deaths {sid}`")
    claims, verdicts = adj.name_rows(sid, ps, rounds, tracks("kill"), tracks("death"),
                                     portraits, board, lineup["sides"]["enemy"],
                                     load_identity_gallery(store.root), death_rows,
                                     lineup["sides"].get("ally", []),
                                     (lineup.get("player") or {}).get("agent"))
    events = identity_events(verdicts, sid)
    rows_named = [{"session_id": sid, "kind": "row_entity", "panel_start_ms": p["start_ms"],
                   "row": k, "entity_id": row.get("entity_id"), "cluster": row.get("cluster"),
                   "death_entity": row.get("death_entity")}
                  for p in ps for k, row in enumerate(p["rows"])]
    # A stream of formal events holds nothing else, so the row-to-entity map
    # is its own stream beside the arbiter's events.
    store.write_events("combat_report_rows", sid, rows_named)
    out = store.write_events("combat_report_identity", sid, events)
    by = {v["entity_id"]: v for v in verdicts}
    covered = sum(1 for r in rows_named if by.get(r["entity_id"], {}).get("status") == "resolved")
    print(f"  identity: {len({r['cluster'] for r in rows_named})} portrait clusters, "
          f"{len(claims)} claims, {sum(v['status'] == 'resolved' for v in verdicts)} named, "
          f"{sum(v['status'] == 'disagreement' for v in verdicts)} disagree; "
          f"{covered}/{len(rows_named)} rows named -> {out}")
    for v in verdicts:
        print(f"    {v['entity_id']}: {v['status']} {v['agent'] or ''} "
              f"{ {ch: r['votes'] for ch, r in v['by_channel'].items()} }")


def cmd_deaths(args) -> int:
    """Death verdicts for every round from stored data only. Decodes no video.

    Writes a `death` stream (a summary with every input's stamp, then one
    `death_verdict` row per killfeed entry keyed by `death_key`) and a
    `death_identity` stream of the formal events. A board interval whose
    independent names repeat an agent adds a `collision` row
    (`board_collisions`), which names no one."""
    from .adjudication.death import (DEATH_ADJUDICATION_VERSION, adjudicate_session_deaths,
                                     death_verdict_to_events, stored_second_life)
    from .adjudication.identity import AGENT_IDENTITY_VERSION, load_identity_gallery
    from .lineup import load_lineup

    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    sid, date = manifest["session_id"], _date_of(manifest)
    portraits = store.read_events("killfeed_portrait", sid)
    if store.events_version("killfeed_portrait", sid) != KILLFEED_PORTRAIT_VERSION:
        raise SystemExit(f"{sid}: killfeed portraits are not at {KILLFEED_PORTRAIT_VERSION} -- "
                         f"run `reticle scan {sid} --only hud`")
    rounds = store.read_rounds(sid, date)
    if rounds is None:
        raise SystemExit(f"{sid}: no stored rounds -- run `reticle rounds {sid}` first")
    rounds = rounds.to_pylist()
    lineup = load_lineup(sid, store.root)
    if not lineup:
        raise SystemExit(f"{sid}: no stored lineup")
    # A stale or missing weapon stream names no weapon; it never blocks deaths.
    weapons = (store.read_events("killfeed_weapon", sid)
               if store.events_version("killfeed_weapon", sid) == KILLFEED_WEAPON_VERSION
               else None)
    if weapons is None:
        print(f"{sid}: no killfeed_weapon stream at {KILLFEED_WEAPON_VERSION}; weapons unnamed "
              f"-- run `reticle scan {sid} --only hud`")
    # A stale or missing name stream leaves every role on its per-entry vote.
    # The name clusters and their assignment were measured in
    # `prototypes/killfeed_name_continuity.py` and `prototypes/match_name_assignment.py`.
    names = (store.read_events("killfeed_name", sid)
             if store.events_version("killfeed_name", sid) == KILLFEED_NAME_VERSION else None)
    if names is None:
        print(f"{sid}: no killfeed_name stream at {KILLFEED_NAME_VERSION}; no name clusters "
              f"-- run `reticle scan {sid} --only hud --from cache`")
    # A name's probability, from each naming channel's measured reliability.
    # It annotates each verdict, and weighs the reference channels in the name
    # clusters' assignment.
    from .adjudication.reliability import RELIABILITY_VERSION, load as load_reliability, name_probability
    rel = load_reliability(store.root)
    res = adjudicate_session_deaths(
        sid, rounds, store.read_hud(sid, date), store.read_roster(sid, date), portraits,
        store.read_events("scoreboard", sid), lineup, load_identity_gallery(store.root),
        source_version=KILLFEED_PORTRAIT_VERSION,
        second_life=stored_second_life(portraits, KILLFEED_PORTRAIT_VERSION),
        weapon_observations=weapons, name_observations=names, reliability=rel)
    common = {"session_id": sid, "source": "death",
              "death_adjudication_version": DEATH_ADJUDICATION_VERSION}
    rows, events = [], []
    for r in res["rounds"]:
        for e, v in zip(r["entries"], r["verdicts"]):
            if rel is not None:
                for key in ("identity", "killer_identity"):
                    if v.metadata.get(key):
                        v.metadata[key]["p_named"] = name_probability(rel, v.metadata[key])
            rows.append({**common, "kind": "death_verdict", "round_no": r["round_no"],
                         "slot": e["slot"], "t_last_ms": e["t_last"],
                         "kf_player_kill": e["kf_player_kill"],
                         "kf_player_death": e["kf_player_death"],
                         "weapon_evidence": e.get("weapon_evidence"),
                         "same_side": e.get("same_side"),
                         "revive_witness": e.get("revive_witness"),
                         "plate_refusal": e.get("plate_refusal"), **v.to_dict()})
            events.extend(death_verdict_to_events(v, sid))
    collisions = [{**common, **c} for r in res["rounds"] for c in r.get("collisions", [])]
    status = lambda key, role: Counter((r["metadata"].get(key) or {}).get("status", "none")
                                       for r in rows)
    head = {**common, "kind": "summary", "deaths": len(rows), "passes": res["passes"],
            "victims": dict(status("identity", "victim")),
            "killers": dict(status("killer_identity", "killer")),
            "weapons": dict(Counter((r.get("weapon_evidence") or {}).get("status", "none")
                                    for r in rows)),
            "revives": sum(bool(r.get("is_revive")) for r in rows),
            "collisions": len(collisions),
            "revive_witnesses": dict(Counter(r["revive_witness"] for r in rows
                                             if r.get("is_revive") and r.get("revive_witness"))),
            "plate_refusals": dict(Counter(r["plate_refusal"] for r in rows if r.get("plate_refusal"))),
            "name_clusters": res.get("name_clusters"),
            "inputs": {"hud": HUD_VERSION, "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
                       "killfeed_weapon": KILLFEED_WEAPON_VERSION if weapons is not None else None,
                       "killfeed_name": KILLFEED_NAME_VERSION if names is not None else None,
                       "scoreboard": store.events_version("scoreboard", sid),
                       "round": rounds[0].get("round_version") if rounds else None,
                       "lineup": lineup.get("version"), "agent_identity": AGENT_IDENTITY_VERSION,
                       "reliability": RELIABILITY_VERSION if rel is not None else None}}
    out = store.write_events("death", sid, [head] + rows + collisions)
    store.write_events("death_identity", sid, events)
    print(f"{sid}: {len(rows) - head['revives']} deaths and {head['revives']} revives over "
          f"{len(rounds)} rounds in {res['passes']} passes; "
          f"victims {head['victims']}, killers {head['killers']}, "
          f"{len(collisions)} board collisions -> {out}")
    return 0


def cmd_plan(args) -> int:
    """Which stored streams the code has moved past, and the least work that
    refreshes them: decode only the stale channels, rerun adjudications from
    storage, and check a reader with a trial before a full scan."""
    from .plan import render, stale
    store = Store(args.store)
    sids = ([_resolve_session(store, args.session)["session_id"]] if args.session
            else [m["session_id"] for m in store.sessions()])
    print(render(stale(store, sids)))
    return 0


def cmd_trial(args) -> int:
    """One reader over part of one session, diffed against the stored streams.
    Writes nothing. `--from cache` decodes nothing."""
    from .trial import run
    store = Store(args.store)
    manifest = _resolve_session(store, args.session)
    between = getattr(args, "between", None)
    res = run(store, manifest, reader=args.reader, source=args.source,
              windows=args.windows, pad_ms=args.pad_ms,
              between=None if between is None else (between[0] * 1000.0, between[1] * 1000.0))
    print(f"{res['session_id']}: {args.reader} from {args.source}, {args.windows} windows: "
          f"{res['frames']} of {res['timeline']} timeline frames in {res['seconds']} s")
    if res["refused"]:
        print(f"  refused {sum(res['refused'].values())} of {res['asked']} frames asked, "
              f"none read: {res['refused']}")
    if res["frame_idx_moved"]:
        print(f"  {res['frame_idx_moved']} frames carry another frame index than the stored "
              f"timeline's; the trial uses the stored one")
    scorer = res.get("portrait_scorer")
    if scorer and scorer["stored"] != scorer["trial"]:
        print(f"  portrait scores come from {scorer['trial']} here and {scorer['stored']} in "
              f"storage; they differ in the fourth decimal (RETICLE_SCOREBOARD picks one)")
    ok = True
    for stream, d in res["diff"].items():
        ok &= d["only_trial"] == 0 and d["only_stored"] == 0
        print(f"  {stream:18s} {d['same']} same, {d['only_trial']} only in trial, "
              f"{d['only_stored']} only stored; {d['stored_outside_frames']} stored rows "
              f"outside the trial's frames")
        if d.get("fields"):
            print(f"    moved fields (rows by observation key): {d['fields']}")
        for ex in d["example_only_trial"][:1]:
            print(f"    trial:  {ex[:240]}")
        for ex in d["example_only_stored"][:1]:
            print(f"    stored: {ex[:240]}")
    print("  identical to storage" if ok else "  DIFFERS from storage")
    return 0 if ok else 1


def _latest_loso() -> dict:
    """The per-name counts of the latest passing `weapon_icons/entries-loso` run."""
    from . import metrics
    rows = [r for r in metrics.load() if r.get("tool") == "weapon_icons"
            and r.get("part") == "entries-loso" and r.get("status") == "pass"]
    return (rows[-1].get("context") or {}).get("by_name", {}) if rows else {}


def cmd_reliability(args) -> int:
    """Per-channel, per-agent identity reliability from stored death verdicts,
    scored where an independent witness named the entity. Decodes no video."""
    from .adjudication.reliability import (RELIABILITY_VERSION, beliefs, icon_heldout_outcomes,
                                           label_outcomes, outcomes,
                                           write as write_reliability)
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    store = Store(args.store)
    rows, used = [], []
    for man in store.sessions():
        d = store.read_events("death", man["session_id"])
        if d and d[0].get("death_adjudication_version") == DEATH_ADJUDICATION_VERSION:
            rows += d[1:]
            used.append(man["session_id"])
    import json
    def last_rows(kind):
        got = {}
        for p in (store.root / "labels" / kind).glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    got[row["key"]] = row
        return list(got.values())
    scored = (outcomes(rows) + label_outcomes(last_rows("feed_portrait"), rows)
              + icon_heldout_outcomes(_latest_loso()))
    table = beliefs(scored)
    print(f"{len(scored)} channel claims scored over {len(used)} sessions ({RELIABILITY_VERSION})")
    for ch, b in table["by_source"].items():
        print(f"  {ch:32s} {b['right']:4d} right {b['wrong']:3d} wrong   mean {b['mean']:.3f}")
    worst = sorted(((k, b) for k, b in table["agents"].items() if b["wrong"]),
                   key=lambda kb: kb[1]["mean"])[:args.top]
    print("least reliable (channel:agent)")
    for k, b in worst:
        print(f"  {k:30s} {b['right']:3d}/{b['right'] + b['wrong']:<3d} mean {b['mean']:.3f}")
    for ch, conf in table["confusions"].items():
        print(f"confusions {ch}: " + ", ".join(f"{k} x{n}" for k, n in list(conf.items())[:8]))
    print("population: " + ", ".join(f"{k} {n}" for k, n in table["population"].items()))
    out = write_reliability(store.root, table, {"death": DEATH_ADJUDICATION_VERSION, "sessions": used})
    print(f"-> {out}")
    return 0


def cmd_smokes(args) -> int:
    """Smoke tracks from stored `minimap_dark` rows, and the ally agent who
    cast each (`adjudication.smoke_owner`). Decodes no video."""
    from .adjudication.smokes import events as smoke_events

    store = Store(args.store)
    sid = _resolve_session(store, args.session)["session_id"]
    rows = store.read_events("minimap_dark", sid)
    if not rows:
        raise SystemExit(f"{sid}: no minimap_dark rows -- run `reticle scan {sid} --only minimap_dark`")
    if rows[0].get("minimap_dark_version") != MINIMAP_DARK_VERSION:
        raise SystemExit(f"{sid}: minimap_dark rows are {rows[0].get('minimap_dark_version')}, "
                         f"current is {MINIMAP_DARK_VERSION} -- re-scan before trusting them")
    with np.load(geometry.path_of(sid, store.root)) as z:
        ref = lighting.reference(z)
    from .menu import stored_menu
    menu, menu_stamp = stored_menu(store, sid)
    out_rows = smoke_events(sid, rows, ref.known, menu.at if menu is not None else None,
                            menu_stamp)
    out = store.write_events("smoke", sid, out_rows)
    head = out_rows[0]
    print(f"{sid}: {head['tracks']} smoke tracks, {head['observed_ends']} with an observed end -> {out}")
    res = _smoke_owners(store, sid, out_rows, float(rows[0].get("hz") or 4.0))
    owners = {r["track"]: r for r in res["rows"][1:]}
    for t in out_rows[1:]:
        o = owners[t["track"]]
        print(f"  {t['first_ms'] / 1000:8.2f}-{t['last_ms'] / 1000:8.2f} s  {t['life_s']:6.2f} s  "
              f"at ({t['cx']:.0f},{t['cy']:.0f}) r {t['r']:.1f}  {t['end_status']}  "
              + (f"{o['agent']} by {'+'.join(o['rules'])}" if o["agent"] else f"refused: {o['reason']}"))
    cov = res["rows"][0]
    print(f"{sid}: team smoke agents {cov['team_smoke_agents']}, player {cov['player_agent']}; "
          f"{cov['named']} of {cov['tracks']} named {cov['by_agent']}, by rule {cov['by_rule']}; "
          f"refused {cov['refused']} -> {res['out']}")
    return 0


def _smoke_owners(store, sid: str, smoke_rows: list[dict], hz: float) -> dict:
    """Name each stored smoke track through `adjudication.smoke_owner` and
    write the `smoke_owner` rows and their formal identity events. Reads the
    tray only where the player's agent is one of the team's smoke agents."""
    from .ability_timeline import stored_gate_inputs
    from .adjudication.smoke_owner import SMOKE_ABILITY, adjudicate, player_smoke_casts
    from .adjudication.ult_cast import lineup_sides, player_agent
    from .lineup import load_lineup
    from .version import TRAY_VERSION

    lineup = load_lineup(sid, store.root)
    player = player_agent(lineup, sid)
    sides = lineup_sides(lineup, sid)
    team = set((sides or {}).get("ally", {}).get("named", [])) & set(SMOKE_ABILITY)
    casts, why = None, "player_not_a_team_smoke_agent"
    if player in team:
        drops = store.read_events("tray_drop", sid)
        if not drops:
            why = "no_tray_drops"
        elif drops[0].get("tray_version") != TRAY_VERSION:
            why = "tray_drops_stale"
        else:
            man = store.read_manifest(sid)
            table = store.read_rounds(sid, _date_of(man))
            rounds = table.to_pylist() if table is not None else []
            gate, _ = stored_gate_inputs(store, sid, _date_of(man), rounds, player)
            casts, why = player_smoke_casts(drops, rounds, **gate), None
    res = adjudicate(sid, smoke_rows, lineup, hz=hz, tray_casts=casts, tray_reason=why)
    out = store.write_events("smoke_owner", sid, res["rows"])
    store.write_events("smoke_owner_identity", sid, res["events"])
    return {**res, "out": out}


def _cache_grid(t_ms, t0: float, t1: float, step_s: float) -> list[float]:
    """Cached times on a regular grid inside [t0, t1] (`roi_cache.grid_times`)."""
    from .roi_cache import grid_times
    return grid_times(t_ms, t0, t1, step_s)


def _sessions_arg(store: Store, args) -> list[str]:
    return ([s["session_id"] for s in store.sessions()] if args.all
            else [_resolve_session(store, args.session)["session_id"]])


def _tray_spans(cache) -> list[list[float]]:
    """The spans `reticle tray` reads: the cache's round spans, or the whole
    cached capture as one span where the cache holds the whole capture (a demo
    or range capture, which has no rounds)."""
    spans = cache.record.get("spans")
    if spans:
        return spans
    return [[float(np.min(cache.t_ms)), float(np.max(cache.t_ms))]] if len(cache.t_ms) else []


def _tray_samples(cache, step_s: float) -> tuple[list, list, list, list]:
    """The tray's slot counts on the crop cache's grid, span by span
    (`_tray_spans`): (times, counts, clean, real). A refused row separates two
    spans, so no drop is read across two rounds; `real` is False on it."""
    from . import tray
    ts, counts, clean, real = [], [], [], []
    for a, b in _tray_spans(cache):
        for smp in cache.samples(_cache_grid(cache.t_ms, a, b, step_s), rois=["hud_abilities"]):
            c, ok = tray.slot_counts(smp.frame)
            ts.append(float(smp.t_ms))
            counts.append(c)
            clean.append(ok)
            real.append(True)
        ts.append((ts[-1] if ts else 0.0) + 10.0)
        counts.append([0, 0, 0, 0])
        clean.append(False)
        real.append(False)
    return ts, counts, clean, real


def cmd_menu(args) -> int:
    """Whether the game's menu covers the HUD, per sample of the stored crops
    (`menu`): the tab strip in the `hud` cache, the CLOSE SETTINGS button in
    the `minimap` cache's tray crop. Decodes no video."""
    from . import menu
    from .roi_cache import ROI_CACHE_VERSION, RoiCache
    from .version import MENU_VERSION

    store = Store(args.store)
    for sid in _sessions_arg(store, args):
        man = store.read_manifest(sid)
        src = man["source"]
        if (int(src["width"]), int(src["height"])) != menu.WH:
            print(f"{sid}: the menu fits are measured at 1920x1080 -- skipped")
            continue
        prof = get_profile(man["source_profile"])
        rows, said = [], []
        hud, why = RoiCache.load(store.root, man, prof, "hud")
        if hud is not None:
            samples = []
            rects = [hud.rect_of(roi) for roi in menu.TAB_ROIS]
            for got in zip(*(hud.crops(roi) for roi in menu.TAB_ROIS)):
                if len({t for _f, t, _c in got}) != 1:
                    raise SystemExit(f"{sid}: the hud cache's crops disagree on their instants")
                fit = (None if any(c is None for _f, _t, c in got) else
                       menu.tab_strip({roi: (c, r) for roi, (_f, _t, c), r
                                       in zip(menu.TAB_ROIS, got, rects)}))
                samples.append((got[0][1], fit))
            rows += menu.menu_rows(sid, "hud", samples, MENU_VERSION, ROI_CACHE_VERSION)
            said.append(f"hud {sum(1 for _t, f in samples if f and f['open'])}/{len(samples)}")
        else:
            said.append(f"hud {why}")
        mm, why = RoiCache.load(store.root, man, prof, "minimap")
        if mm is not None:
            rect = mm.rect_of(menu.TRAY_ROI)
            x0, y0, x1, y1 = rect
            spans = mm.record.get("spans") or [(float(mm.t_ms.min()), float(mm.t_ms.max()))]
            samples = []
            for a, b in spans:
                for smp in mm.samples(_cache_grid(mm.t_ms, a, b, args.step), rois=[menu.TRAY_ROI]):
                    samples.append((float(smp.t_ms),
                                    menu.close_button(smp.frame[y0:y1, x0:x1], rect)))
            rows += menu.menu_rows(sid, "minimap", samples, MENU_VERSION, ROI_CACHE_VERSION)
            said.append(f"tray {sum(1 for _t, f in samples if f['open'])}/{len(samples)}")
        else:
            said.append(f"tray {why}")
        if not rows:
            print(f"{sid}: no crop cache ({'; '.join(said)}) -- nothing written")
            continue
        out = store.write_events("menu_open", sid, rows)
        print(f"{sid}: menu open on {'; '.join(said)} samples -> {out}")
    return 0


def cmd_tray(args) -> int:
    """The tray's charge drops from the stored crops, and which are the player's
    casts (`ability_timeline.player_tray_casts`). A session with no rounds
    table is read as one span, and its drops are `no_rounds` unless the stored
    menu witness covers them (`menu_open` wins). Decodes no video."""
    from . import tray
    from .ability_timeline import player_tray_casts, stored_gate_inputs
    from .adjudication.ult_cast import player_agent
    from .lineup import load_lineup
    from .menu import stored_menu
    from .roi_cache import RoiCache
    from .version import PLAYER_CAST_VERSION, TRAY_VERSION

    store = Store(args.store)
    for sid in _sessions_arg(store, args):
        man = store.read_manifest(sid)
        src = man["source"]
        if (int(src["width"]), int(src["height"])) != (1920, 1080):
            print(f"{sid}: tray geometry is measured at 1920x1080 -- skipped")
            continue
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
        if cache is None:
            print(f"{sid}: no minimap crop cache ({why}) -- skipped")
            continue
        ts, counts, clean, real = _tray_samples(cache, args.step)
        drops = tray.drops(ts, np.asarray(counts, float), np.asarray(clean, bool))
        date = _date_of(man)
        table = store.read_rounds(sid, date)
        if table is None:
            # No rounds table (a demo or range capture): the gate reads no HUD,
            # deaths or kit witness, and refuses every drop as `no_rounds`
            # unless the menu witness covers it, which wins (`menu_open`).
            menu_w, menu_stamp = stored_menu(store, sid)
            rows = player_tray_casts(drops, None, None, [],
                                     menu_at=menu_w.at if menu_w is not None else None)
            stamps = {"tray_kit": "no_rounds", "menu_open": menu_stamp}
        else:
            rounds = table.to_pylist()
            gate, stamps = stored_gate_inputs(store, sid, date, rounds,
                                              player_agent(load_lineup(sid, store.root), sid))
            rows = player_tray_casts(
                drops, gate["phase_of"], rounds, gate["player_deaths_ms"], agent=gate["agent"],
                second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
                report_deaths=gate["report_deaths"], kit_changes_ms=gate["kit_changes_ms"],
                kit_returns_ms=gate["kit_returns_ms"], menu_at=gate["menu_at"])
        common = {"session_id": sid, "tray_version": TRAY_VERSION,
                  "player_cast_version": PLAYER_CAST_VERSION, "step_s": args.step}
        why_not = Counter(r["reason"] for r in rows if not r["player_cast"])
        out_rows = [{**common, "kind": "coverage", "samples": sum(real),
                     "spans": "rounds" if cache.record.get("spans") else "whole_capture",
                     "tray_kit": stamps["tray_kit"], "menu_open": stamps["menu_open"],
                     "drops": len(rows), "player_casts": sum(r["player_cast"] for r in rows),
                     "refused_reasons": dict(sorted(why_not.items()))}]
        out_rows += [{**common, "kind": "drop", **r} for r in rows]
        out = store.write_events("tray_drop", sid, out_rows)
        print(f"{sid}: {len(rows)} drops, {out_rows[0]['player_casts']} the player's casts; "
              f"refused {dict(why_not)} -> {out}")
    return 0


def _tray_frames(cache, step_s: float):
    """(cache span index, Sample) on the crop cache's grid, span by span: the
    grid `reticle tray` samples, so a kit sample and a fill share an instant."""
    for si, (a, b) in enumerate(cache.record["spans"]):
        for smp in cache.samples(_cache_grid(cache.t_ms, a, b, step_s), rois=["hud_abilities"]):
            yield si, smp


def cmd_widget_fit(args) -> int:
    """Fit where the session draws its minimap widget against the baked static
    (`widget_frame`), from the stored minimap crops. Decodes no video.

    `--write` stores the placement on the manifest with its stamp, tags a
    non-identity one `minimap:variant`, and names a capture box when the
    profile's crop cannot hold the widget -- which makes the minimap cache
    stale until a re-decode stores the wider crop. A previous placement is
    kept under `minimap_widget_history`, never overwritten."""
    import json

    from . import geometry
    from . import widget_frame as wf
    from .roi_cache import RoiCache

    store = Store(args.store)
    man = _resolve_session(store, args.session)
    sid = man["session_id"]
    profile = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        # A stored placement the crop cannot hold refuses the cache it would
        # normalise; the fit reads raw crops, so read it without the placement.
        bare = {k: v for k, v in man.items() if k != wf.MANIFEST_KEY}
        cache, why2 = RoiCache.load(store.root, bare, profile, "minimap")
        if cache is None:
            raise SystemExit(f"{sid}: no minimap cache ({why}; {why2})")
    got = wf.fit_session(man, cache, store.root, n=args.frames)
    segs = got["segments"]
    if not segs:
        raise SystemExit(f"{sid}: no cached frame reached ncc {wf.MIN_NCC}")
    with np.load(geometry.require(sid, store.root)) as z:
        baked_roi = [int(v) for v in z["roi"]]
    wh = (int(man["source"]["width"]), int(man["source"]["height"]))
    variant = any(not wf.is_identity(sg["affine"], baked_roi) for sg in segs)
    need = wf.needed_box(segs, got["shape"], wh)
    held = got["box"]
    fits = (need[0] >= held[0] and need[1] >= held[1]
            and need[2] <= held[2] and need[3] <= held[3])
    print(f"{sid}  {man['source']['path']}")
    print(f"fitted     {got['frames']} cached frames in {held}")
    for sg in segs:
        a = np.asarray(sg["affine"])
        print(f"  from {sg['t0_ms']} to {sg['t1_ms']} ms: rotation {sg['rotation']}, "
              f"scale {sg['scale']:.3f}, corner ({a[0, 2]:.1f}, {a[1, 2]:.1f}), "
              f"{sg['n']} frames, ncc >= {sg['ncc_min']:.3f}")
    print(f"placement  {'VARIANT' if variant else 'identity'}; the whole widget needs "
          f"{need}, the cache holds {held}"
          + ("" if fits else " -- the crop clips the widget"))
    if not args.write:
        return 0
    if not variant:
        print("identity   nothing stored: the session reads the baked placement")
        return 0
    box = wf.capture_box(man) if fits else need
    rec = wf.record(segs, geometry.key_of(sid, store.root), baked_roi, box,
                    f"roi_cache {cache.record['version']} rect {held}", got["frames"])
    if man.get(wf.MANIFEST_KEY):
        man.setdefault(wf.MANIFEST_KEY + "_history", []).append(man[wf.MANIFEST_KEY])
    man[wf.MANIFEST_KEY] = rec
    if wf.VARIANT_TAG not in man.setdefault("tags", []):
        man["tags"].append(wf.VARIANT_TAG)
    store.manifest_path(sid).write_text(json.dumps(man, indent=2), encoding="utf-8")
    print(f"stored     {wf.MANIFEST_KEY} ({wf.WIDGET_FRAME_VERSION}) and tag "
          f"{wf.VARIANT_TAG} on {store.manifest_path(sid)}")
    if box is not None and box != held:
        print(f"capture    box {box}: the minimap cache is stale until "
              f"`reticle scan {sid} --only roi_cache --cache-roi minimap` re-decodes it")
    return 0


def cmd_self_icon(args) -> int:
    """The minimap self icon's portrait scored against the agents' art, on
    stored minimap crops where the roster reads all five allies alive
    (`self_icon`); the lineup reads the rows as its `self_icon` witness.
    Decodes no video."""
    import time

    from .adjudication.identity import load_ally_portrait_references
    from .lineup import load_gallery
    from .self_icon import read_session

    store = Store(args.store)
    gal = load_gallery(store.root)
    references = load_ally_portrait_references(store.root)
    sids = ([p.stem for p in sorted((store.root / "lineups").glob("*.json"))] if args.all
            else _sessions_arg(store, args))
    for sid in sids:
        t0 = time.perf_counter()
        res = read_session(store, sid, gal, references, args.step)
        if "skipped" in res:
            print(f"{sid}: {res['skipped']} -- skipped")
            continue
        head = res["rows"][0]
        head["checks"] = {"wall_s": round(time.perf_counter() - t0, 1)}
        out = store.write_events("self_icon", sid, res["rows"])
        w = head["witness"]
        print(f"{sid}: {head['scored']} of {head['grid_frames']} grid frames scored; "
              f"refused {head['refused']}; witness {w['frames']} frames "
              f"({w.get('reference_source')})"
              f"{'' if w['frames'] else ' (' + w.get('reason', '') + ')'}; "
              f"{head['checks']['wall_s']} s -> {out}")
    return 0


def _stored_alive(store, sid: str, man: dict):
    """The stored roster's times and ally alive counts (-1 unread), or empty."""
    import glob

    import pyarrow.parquet as pq

    path = store.roster_path(sid, man["ingested_at"][:10])
    if not path.is_file():
        found = glob.glob(str(store.root / "l1" / "roster" / "*" / f"session={sid}" / "*.parquet"))
        path = found[-1] if found else None
    if path is None:
        return [], []
    table = pq.read_table(path, columns=["t_ms", "alive_ally"])
    return (table.column("t_ms").to_pylist(),
            [(-1 if a is None else int(a)) for a in table.column("alive_ally").to_pylist()])


def _spike_session(store, sid: str, step_s: float) -> dict:
    """Every grid frame of the session's minimap crop cache, read by
    `spike.read_frame`, with the roster marker (`spike.roster_marker`) from
    the hud crop cache where one is stored.

    Returns `{"rows": [...]}`, a coverage row first and a row per grid frame,
    or `{"skipped": why}`. Decodes no video."""
    import cv2

    from . import geometry
    from .minimap import floor_mask, slab_mask, widget_scale
    from .profiles import get_profile
    from .roi_cache import RoiCache
    from .spike import (AMP_MIN, AMP_PARTIAL, MARK_NCC_MIN, NCC_MIN, NCC_STRONG, ROSTER_GAP_MS,
                        SIDES, read_frame, roster_marker)
    from .version import SPIKE_VERSION

    man = store.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    mm, why = RoiCache.load(store.root, man, prof, "minimap")
    if mm is None:
        return {"skipped": f"no minimap crop cache ({why})"}
    hud, hud_why = RoiCache.load(store.root, man, prof, "hud")
    try:
        med = geometry.reference_static(sid, store.root)
    except SystemExit as e:                  # `geometry.require` exits with the reason
        return {"skipped": f"no baked geometry ({e})"}
    sd = geometry.stability(sid, store.root, med.shape[:2])
    ctx = {"floor": floor_mask(med, sd=sd), "slab": slab_mask(med, sd=sd), "static": med,
           "sgray": cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)}
    t = np.unique(np.asarray(mm.t_ms, float))
    spans = mm.record.get("spans") or [[float(t[0]), float(t[-1])]]
    grid: list[float] = []
    for a, b in spans:
        ts = t[(t >= a) & (t <= b)]
        if len(ts):
            want = np.arange(ts[0], ts[-1] + 1, step_s * 1000.0)
            grid += [float(x) for x in ts[np.unique(np.searchsorted(ts, want).clip(0, len(ts) - 1))]]
    grid = sorted(set(grid))
    ht = np.unique(np.asarray(hud.t_ms, float)) if hud is not None else np.array([])
    pair = {}
    for g in grid:
        if len(ht):
            j = int(np.argmin(np.abs(ht - g)))
            if abs(ht[j] - g) <= ROSTER_GAP_MS:
                pair[g] = float(ht[j])
    marks = {}
    if hud is not None and pair:
        rx0, ry0, rx1, ry1 = hud.rect_of("hud_roster")
        for smp in hud.samples(sorted(set(pair.values())), rois=["hud_roster"]):
            marks[float(smp.t_ms)] = roster_marker(smp.frame[ry0:ry1, rx0:rx1])
    x0, y0, x1, y1 = mm.rect_of("minimap")

    def rotation(t_ms: float) -> int:
        # The placement turns the map, not the upright glyph (`spike`).
        seg = mm.widget.at(t_ms) if mm.widget is not None else None
        return int(seg["rotation"]) if seg is not None else 0

    frames = []
    for smp in mm.samples(grid, rois=["minimap"]):
        row = {"kind": "frame", "t_ms": float(smp.t_ms), "frame_idx": int(smp.frame_idx),
               **read_frame(smp.frame[y0:y1, x0:x1], {**ctx, "rotation": rotation(smp.t_ms)})}
        h = pair.get(float(smp.t_ms))
        row["roster_t_ms"] = h
        row["marker"] = (marks.get(h) if h is not None else
                         {"slot": None, "reason": "no_hud_cache" if hud is None else "no_roster_sample"})
        frames.append(row)
    frames.sort(key=lambda r: r["t_ms"])
    read = [r for r in frames if r["reason"] is None]
    head = {"kind": "coverage", "session": sid, "spike_version": SPIKE_VERSION,
            "widget_scale": round(widget_scale(x1 - x0), 4),
            "roi_cache_version": mm.record.get("version"),
            "hud_cache": None if hud is None else hud.record.get("version"),
            "hud_cache_reason": hud_why,
            "parameters": {"step_s": step_s, "SIDES": SIDES, "NCC_MIN": NCC_MIN,
                           "AMP_MIN": AMP_MIN, "NCC_STRONG": NCC_STRONG,
                           "AMP_PARTIAL": AMP_PARTIAL, "MARK_NCC_MIN": MARK_NCC_MIN,
                           "ROSTER_GAP_MS": ROSTER_GAP_MS},
            "grid_frames": len(frames), "read": len(read),
            "rotation_frames": {str(k): sum(r.get("rotation", 0) == k for r in read)
                                for k in sorted({r.get("rotation", 0) for r in read})},
            "refused": {k: sum(r["reason"] == k for r in frames)
                        for k in ("widget_not_drawn", "crop_size")},
            "glyph_frames": {s: sum(any(g["reason"] is None and g["state"] == s
                                        for g in r["glyphs"]) for r in read)
                             for s in ("dropped", "carried")},
            "marker_frames": sum((r["marker"] or {}).get("slot") is not None for r in frames),
            "marker_read": sum((r["marker"] or {}).get("reason") in (None, "no_marker")
                               for r in frames)}
    for r in frames:
        r["spike_version"] = SPIKE_VERSION
    return {"rows": [head] + frames}


def cmd_spike(args) -> int:
    """The spike's glyph on the minimap and marker on the roster, from the
    stored crops (`spike`), then its carrier cross-checked against the plant
    and the roster (`adjudication.spike_carrier`). Decodes no video;
    `--from-store` reruns only the cross-check from stored `spike` rows."""
    import time

    from .adjudication.spike_carrier import check
    from .version import SPIKE_VERSION

    store = Store(args.store)
    sids = _sessions_arg(store, args)
    for sid in sids:
        t0 = time.perf_counter()
        if not args.from_store:
            res = _spike_session(store, sid, args.step)
            if "skipped" in res:
                print(f"{sid}: {res['skipped']} -- skipped")
                continue
            head = res["rows"][0]
            head["checks"] = {"wall_s": round(time.perf_counter() - t0, 1)}
            out = store.write_events("spike", sid, res["rows"])
            print(f"{sid}: {head['read']} of {head['grid_frames']} grid frames read; glyph frames "
                  f"{head['glyph_frames']}; marker on {head['marker_frames']} of "
                  f"{head['marker_read']} roster reads; {head['checks']['wall_s']} s -> {out}")
        rows = store.read_events("spike", sid)
        if not rows or rows[0].get("spike_version") != SPIKE_VERSION:
            print(f"{sid}: no current `spike` rows -- run `reticle spike {sid}`")
            continue
        man = store.read_manifest(sid)
        rs = store.read_rounds(sid, man["ingested_at"][:10])
        rt, ra = _stored_alive(store, sid, man)
        got = check(rows, None if rs is None else rs.to_pylist(), rt, ra)
        out = store.write_events("spike_carrier", sid, got)
        c = got[0]
        print(f"{sid}: both read on {c['both_read']} frames, agree {c['agree']}; "
              f"disagreements {c['disagreements']}; carrier seen on {c['rounds_carrier_seen']} "
              f"of {c['rounds']} rounds; losses {c['losses_by_witness']} -> {out}")
    return 0


def cmd_tray_kit(args) -> int:
    """Whose kit the tray shows, per sample of the stored `hud_abilities`
    crops (`adjudication.tray_kit`), the slot icons scored against the
    catalogue's (`tray_icons`). Decodes no video."""
    import time

    from . import tray, tray_icons
    from .adjudication.tray_kit import adjudicate, candidate_sets, read_sample
    from .lineup import load_lineup
    from .roi_cache import RoiCache
    from .version import TRAY_KIT_VERSION, TRAY_VERSION

    store = Store(args.store)
    icons = tray_icons.load_slot_icons(store.root)
    all_agents = sorted(icons)
    ref_key = tray_icons.reference_key(store.root)
    parameters = {"ICON_PX": tray_icons.ICON_PX, "ICON_CY": tray_icons.ICON_CY,
                  "SHIFT_PX": tray_icons.SHIFT_PX, "step_s": args.step,
                  "rate": f"the crop cache's grid every {args.step} s inside its round spans, "
                          f"the grid `reticle tray` and `reticle ability-state` read"}
    done = []
    for sid in _sessions_arg(store, args):
        t0 = time.perf_counter()
        man = store.read_manifest(sid)
        src = man["source"]
        if (int(src["width"]), int(src["height"])) != (1920, 1080):
            print(f"{sid}: tray geometry is measured at 1920x1080 -- skipped")
            continue
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
        if cache is None or not cache.record.get("spans"):
            print(f"{sid}: no minimap crop cache with round spans ({why}) -- skipped")
            continue
        lineup = load_lineup(sid, store.root)
        sets = candidate_sets(lineup, sid)
        ts, span_of, counts, clean, patches = [], [], [], [], []
        for si, smp in _tray_frames(cache, args.step):
            c, ok = tray.slot_counts(smp.frame)
            ts.append(float(smp.t_ms))
            span_of.append(si)
            counts.append(c)
            clean.append(ok)
            patches.append([np.clip(p, 0, 255).astype(np.uint8)
                            for p in tray_icons.slot_patches(smp.frame)])
        t_read = time.perf_counter() - t0
        fills = tray.fills(np.asarray(counts, float), np.asarray(clean, bool))
        samples = []
        for i, t in enumerate(ts):
            got: dict = {}
            p = [x.astype(np.float32) for x in patches[i]]

            def score(agents, p=p, got=got):
                new = [a for a in agents if a not in got]
                if new:
                    got.update(zip(new, tray_icons.slot_scores(p, icons, new)))
                return np.array([got[a] for a in agents])

            drawn = tray.drawn(fills[i])
            samples.append({"t_ms": t, "cache_span": span_of[i], "drawn": drawn,
                            **read_sample(drawn, score, sets, all_agents)})
        inputs = {"roi_cache": cache.record.get("version"), "tray_fill": TRAY_VERSION,
                  "lineup": (lineup or {}).get("version"),
                  "board_state": (lineup or {}).get("board_state"),
                  "catalogue": f"reference/abilities.json#{ref_key}"}
        res = adjudicate(sid, samples, sets, inputs, parameters)
        cov = res["rows"][0]
        cov["checks"] = {"cache_read_s": round(t_read, 1),
                         "wall_s": round(time.perf_counter() - t0, 1)}
        out = store.write_events("tray_kit", sid, res["rows"])
        store.write_events("tray_kit_identity", sid, res["events"])
        print(f"{sid}: player {cov['player_agent']}; {cov['named']} of {cov['samples']} samples "
              f"named {cov['named_by_agent']}; refused {cov['refused']}; {cov['spans']} spans, "
              f"{cov['kit_changes']} kit changes, {cov['kit_returns']} returns; "
              f"{cov['checks']['wall_s']} s -> {out}")
        done.append((sid, man, res["rows"]))
    if args.record and done:
        from . import metrics
        for sid, man, rows in done:
            values = _tray_kit_values(store, sid, man, rows, args.at)
            metrics.record(tool="tray_kit", part="witness", session=sid, values=values,
                           deps={"tray_kit_version": TRAY_KIT_VERSION,
                                 "tray_version": TRAY_VERSION,
                                 "catalogue": rows[0]["inputs"]["catalogue"]},
                           context={"at_s": list(args.at or [])})
            print(f"recorded tray_kit/witness@{sid}: {json.dumps(values)}")
    return 0


def _tray_kit_values(store, sid: str, man: dict, rows: list[dict], at_s) -> dict:
    """The quoted numbers of one `tray-kit --record` run: coverage, the
    reading at the instants asked for, and, where the killfeed witnesses the
    player's deaths, each death's delay to the first sample of another kit and
    the kit changes while the player lives (`ability_timeline.kit_windows`)."""
    from .ability_timeline import DEATH_LEAD_MS, kit_windows, round_window_of, stored_gate_inputs
    cov = rows[0]
    samples = [r for r in rows if r.get("kind") == "sample"]
    step = float(cov["parameters"]["step_s"])
    values = {"samples": cov["samples"], "named": cov["named"], "spans": cov["spans"],
              "spans_own": cov["spans_own"], "spans_other": cov["spans_other"],
              "kit_changes": cov["kit_changes"], "kit_returns": cov["kit_returns"],
              **{f"named_{k.replace('/', '_')}": v for k, v in cov["named_by_agent"].items()},
              **{f"set_{k}": v for k, v in cov["named_by_set"].items()},
              **{f"refused_{k}": v for k, v in cov["refused"].items()}}
    t = np.array([s["t_ms"] for s in samples])
    for s_at in at_s or []:
        s = samples[int(np.argmin(np.abs(t - s_at * 1000.0)))]
        key = f"at_{str(s_at).replace('.', '_')}_s"
        values[key] = s["kit_agent"] or f"refused_{s['reason']}"
        values[f"{key}_t_ms"] = s["t_ms"]
    player = cov["player_agent"]
    date = _date_of(man)
    rounds = store.read_rounds(sid, date).to_pylist()
    gate, _stamps = stored_gate_inputs(store, sid, date, rounds, player)
    values["killfeed_deaths"] = len(gate["player_deaths_ms"])
    if not gate["player_deaths_ms"] or player is None:
        return values
    # The killfeed's kit ends alone: the witness is scored against the
    # channel it does not read.
    kits = kit_windows(rounds, gate["player_deaths_ms"], agent=gate["agent"],
                       second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
                       report_deaths=gate["report_deaths"])
    other = [s for s in samples if s["kit_agent"] and s["kit_agent"] != player]
    changes = [r for r in rows if r.get("kind") == "kit_change"]
    delays, unseen, live_ms, early = [], [], 0.0, []
    for s in samples:
        k = round_window_of(s["t_ms"], kits)
        if k is not None and (k["kit_end_ms"] is None
                              or s["t_ms"] < k["kit_end_ms"] - DEATH_LEAD_MS):
            live_ms += step * 1000.0
    for k in kits:
        end = k["kit_end_ms"]
        if end is None:
            continue
        _a, _z, close = k["window"]
        inside = [s["t_ms"] for s in other if end - DEATH_LEAD_MS <= s["t_ms"] <= close]
        if inside:
            delays.append((min(inside) - end) / 1000.0)
        else:
            unseen.append(end)
    for c in changes:
        k = round_window_of(c["kit_change_ms"], kits)
        if k is not None and (k["kit_end_ms"] is None
                              or c["kit_change_ms"] < k["kit_end_ms"] - DEATH_LEAD_MS):
            early.append(c["kit_change_ms"])
    values.update({"kill_ends": len(delays) + len(unseen),
                   "kill_ends_with_other_kit": len(delays),
                   "kill_ends_without_other_kit": len(unseen),
                   "kill_ends_without_other_kit_t_s": [round(x / 1000.0, 2) for x in unseen],
                   "live_min": round(live_ms / 60000.0, 2),
                   "changes_while_alive": len(early),
                   "changes_while_alive_per_live_min": round(
                       len(early) / max(live_ms / 60000.0, 1e-9), 4),
                   "changes_while_alive_t_s": [round(x / 1000.0, 1) for x in early]})
    if delays:
        q = np.quantile(delays, [0.0, 0.25, 0.5, 0.75, 1.0])
        values.update({f"delay_s_{n}": round(float(x), 2)
                       for n, x in zip(("min", "q25", "median", "q75", "max"), q)})
        values["delays_s"] = [round(d, 2) for d in sorted(delays)]
    return values


def cmd_ability_state(args) -> int:
    """The player's kit as a state per slot (`adjudication.ability_state`):
    the stored `tray_drop` rows, the gate's verdicts on them, the deaths, and
    the tray fills reread from the stored `hud_abilities` crops on the grid
    `reticle tray` sampled, which carry what the drops cannot (the level
    between drops, an equip, a lit X bar, every rise). The wiki harvest
    (`reference/abilities.json`) is the charge prior where no domain fact
    gives a count (`charge_priors`). Decodes no video."""
    import json
    import time

    from . import domain, tray
    from .ability_timeline import kit_windows, player_tray_casts, stored_gate_inputs
    from .adjudication.ability_state import (CATALOGUE_PATH, adjudicate, player_agent_verdict,
                                             player_kit, slot_parameters)
    from .adjudication.tray_kit import stored_kit_witness
    from .adjudication.ult_cast import DROP_FIELDS
    from .lineup import load_lineup
    from .roi_cache import RoiCache
    from .version import ABILITY_STATE_VERSION, PLAYER_CAST_VERSION, TRAY_VERSION

    store = Store(args.store)
    facts = domain.load()
    # The charge prior: the harvest, stamped by its date, or its stated absence.
    cat_file = store.root / CATALOGUE_PATH
    catalogue = (json.loads(cat_file.read_text(encoding="utf-8")) if cat_file.is_file()
                 else None)
    cat_stamp = (f"{CATALOGUE_PATH}@{catalogue.get('harvested')}" if catalogue is not None
                 else f"absent:{CATALOGUE_PATH}")
    if catalogue is None:
        print(f"no charge prior: {cat_file} is absent; slots without a fact stay unread "
              f"and the kit names no ability")
    done = []
    for sid in _sessions_arg(store, args):
        t0 = time.perf_counter()
        stored = store.read_events("tray_drop", sid)
        cov = next((r for r in stored if r.get("kind") == "coverage"), None)
        if cov is None:
            print(f"{sid}: no tray_drop rows -- skipped")
            continue
        if cov.get("tray_version") != TRAY_VERSION:
            print(f"{sid}: tray_drop is {cov.get('tray_version')}, code is {TRAY_VERSION} "
                  f"-- rerun `reticle tray`; skipped")
            continue
        man = store.read_manifest(sid)
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
        if cache is None or not cache.record.get("spans"):
            print(f"{sid}: no minimap crop cache with round spans ({why}) -- skipped")
            continue
        drops = [r for r in stored if r.get("kind") == "drop"]
        ts, counts, clean, real = _tray_samples(cache, cov["step_s"])
        counts, clean = np.asarray(counts, float), np.asarray(clean, bool)
        t_read = time.perf_counter() - t0
        # The reread must give the stored drops, or the fills are not theirs.
        key = lambda r: tuple(r[k] for k in ("t_ms", "slot", "from", "to", "forced",
                                              "cooccur", "across_gap"))
        reread_mismatch = len(set(map(key, tray.drops(ts, counts, clean)))
                              ^ set(map(key, drops)))
        fills = tray.fills(counts, clean)
        keep = np.asarray(real, bool)
        date = _date_of(man)
        rounds = store.read_rounds(sid, date)
        round_version = (rounds.schema.metadata or {}).get(b"round_version", b"").decode() or None
        rounds = rounds.to_pylist()
        lineup = load_lineup(sid, store.root)
        agent = player_agent_verdict(lineup, sid)
        gate, stamps = stored_gate_inputs(store, sid, date, rounds, agent["agent"])
        gate_rows = player_tray_casts(
            [{k: r[k] for k in DROP_FIELDS} for r in drops], gate["phase_of"], rounds,
            gate["player_deaths_ms"], agent=gate["agent"],
            second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
            report_deaths=gate["report_deaths"], kit_changes_ms=gate["kit_changes_ms"],
            kit_returns_ms=gate["kit_returns_ms"], menu_at=gate["menu_at"])
        kits = kit_windows(rounds, gate["player_deaths_ms"], agent=gate["agent"],
                           second_lives_ms=gate["second_lives_ms"],
                           revives_ms=gate["revives_ms"], report_deaths=gate["report_deaths"],
                           kit_changes_ms=gate["kit_changes_ms"],
                           kit_returns_ms=gate["kit_returns_ms"])
        spectated = stored_kit_witness(store.read_events("tray_kit", sid),
                                       agent=agent["agent"])["other_spans"]
        # The kit's names come from the same harvest (`lineup.abilities_for`).
        kit = player_kit(agent["agent"], store.root) if catalogue is not None else {}
        inputs = {**stamps, "tray_drop": cov["tray_version"], "catalogue": cat_stamp,
                  "tray_drop_player_cast": cov.get("player_cast_version"),
                  "tray_fill": TRAY_VERSION, "roi_cache": cache.record.get("version"),
                  "round": round_version, "lineup": (lineup or {}).get("version"),
                  "agent_identity": agent["adjudication_version"]}
        checks = {"step_s": cov["step_s"], "drops_reread_mismatch": reread_mismatch,
                  "gate_stored_mismatch": sum(
                      (a["reason"], a["player_cast"]) != (b.get("reason"), b.get("player_cast"))
                      for a, b in zip(gate_rows, drops)),
                  "cache_read_s": round(t_read, 1)}
        rows = adjudicate(
            sid, drops=drops, gate_rows=gate_rows, kits=kits, phase_of=gate["phase_of"],
            samples={"t_ms": [t for t, r in zip(ts, real) if r], "fills": fills[keep],
                     "drawn": [tray.drawn(f) for f in fills[keep]], "clean": clean[keep]},
            agent=agent, params=slot_parameters(agent["agent"], kit, facts, catalogue=catalogue),
            inputs=inputs, checks=checks, spectated=spectated)
        rows[0]["checks"]["wall_s"] = round(time.perf_counter() - t0, 1)
        out = store.write_events("ability_state", sid, rows)
        c = rows[0]
        print(f"{sid}: {agent['agent']} ({agent['status']}); {c['readable_slot_samples']} of "
              f"{c['slot_samples']} slot-samples readable; {c['by_transition']}; surprises "
              f"{c['surprises']}; reread mismatch {reread_mismatch}, gate mismatch "
              f"{checks['gate_stored_mismatch']}; counts from {c['charges_source']}, "
              f"conflicts {len(c['charge_conflicts'])}, without a count "
              f"{[x['slot'] for x in c['slots_without_count']]}; "
              f"{rows[0]['checks']['wall_s']} s -> {out}")
        done.append((sid, rows))
    if args.record and done:
        from . import metrics
        values = _ability_state_values(store, done)
        metrics.record(tool="ability_state", part="step1",
                       session=args.session if not args.all else "all-sessions",
                       values=values,
                       deps={"ability_state_version": ABILITY_STATE_VERSION,
                             "tray_version": TRAY_VERSION,
                             "player_cast_version": PLAYER_CAST_VERSION},
                       context={"labels": "labels/tray_object", "catalogue": cat_stamp,
                                "sessions": [sid for sid, _ in done]})
        print(json.dumps(values, indent=1))
    return 0


def _ability_state_values(store, done) -> dict:
    """The quoted numbers of one `ability-state --record` run: coverage, the
    unreadable reasons, the invariant counts, the charge counts' sources and
    conflicts, the half readings against each count, and the player's labels."""
    import json

    from .adjudication.ability_state import EQUIP_MIN, score_labels
    pooled, invariants, unread, reasons = Counter(), Counter(), Counter(), Counter()
    labelled = []
    sources, slot_source, conflicts, without, segments = Counter(), {}, {}, {}, {}
    for sid, rows in done:
        c = rows[0]
        # Where an equipped slot's fill sits: the stored releases' `from`.
        released = [r["from"] for r in store.read_events("tray_drop", sid)
                    if r.get("kind") == "drop" and r.get("reason") == "equip_release"]
        pooled.update({"release_drops": len(released),
                       "release_from_at_equip_min": sum(f >= EQUIP_MIN for f in released)})
        pooled.update({"sessions": 1, "samples": c["samples"], "slot_samples": c["slot_samples"],
                       "readable_slot_samples": c["readable_slot_samples"],
                       "drops": c["drops"],
                       "drops_reread_mismatch": c["checks"]["drops_reread_mismatch"],
                       "gate_stored_mismatch": c["checks"]["gate_stored_mismatch"]})
        pooled.update({f"transition_{k}": v for k, v in c["by_transition"].items()})
        pooled.update({f"surprise_{k}": v for k, v in c["surprises"].items()})
        pooled.update({f"kit_witness_{k}": v for k, v in c.get("kit_witness", {}).items()})
        unread.update(c["unreadable_slot_samples"])
        reasons.update(c["charges_unread_readable_slot_samples"])
        # Where each count came from, per distinct agent and slot.
        sources.update(c["charges_source_readable_slot_samples"])
        who = c["agent"].get("agent")
        for slot, src in c["charges_source"].items():
            if who and src:
                slot_source[f"{who}:{slot}"] = src
        for x in c["charge_conflicts"]:
            conflicts[f"{who}:{x['slot']}"] = (f"{who}:{x['slot']}:{x['kind']}:player={x['player']}"
                                               f":catalogue={x['catalogue']}:{x['fact']}")
        for x in c["slots_without_count"]:
            if who:
                without[f"{who}:{x['slot']}"] = f"{who}:{x['slot']}:{x['prior_reason'] or x['reason']}"
        for slot, seg in c["segments"].items():
            k = f"{who}:{slot}"
            got = segments.setdefault(k, {"max_charges": seg["max_charges"],
                                          "source": seg["source"], "half_samples": 0,
                                          "agree": 0, "disagree": 0, "unscored": 0})
            for f in ("half_samples", "agree", "disagree", "unscored"):
                got[f] += seg[f]
        for k, v in c["invariants"].items():
            if isinstance(v, int):
                invariants[k] += v
                if v:
                    invariants[f"{k}_{sid}"] = v
        path = store.root / "labels" / "tray_object" / f"{sid}.jsonl"
        if path.exists():
            labs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            labelled += score_labels(rows, labs)["labels"]
    values = dict(sorted(pooled.items()))
    values["readable_fraction"] = round(values["readable_slot_samples"]
                                        / max(values["slot_samples"], 1), 4)
    values.update({f"unreadable_{k}": v for k, v in sorted(unread.items())})
    # The kit reasons again under names a citation can carry (an identifier).
    values.update({f"unreadable_{k.replace(':', '_')}": unread.get(k, 0)
                   for k in ("kit_frozen:after_player_death", "kit:spectating",
                             "owner_dead:kit_witness")})
    values["unreadable_fraction"] = round(1 - values["readable_fraction"], 4)
    values.update({f"charges_unread_{k}": v for k, v in sorted(reasons.items())})
    values.update({f"invariant_{k}": v for k, v in sorted(invariants.items())})
    values.update({
        "charges_source_player": sources.get("player", 0),
        "charges_source_catalogue": sources.get("catalogue", 0),
        "charges_source_catalogue_confirmed": sources.get("catalogue-confirmed", 0),
        "slots_source_player": sum(v == "player" for v in slot_source.values()),
        "slots_source_catalogue": sum(v == "catalogue" for v in slot_source.values()),
        "slots_source_catalogue_confirmed": sum(v == "catalogue-confirmed"
                                                for v in slot_source.values()),
        "charge_conflicts": len(conflicts),
        "charge_conflict_slots": [conflicts[k] for k in sorted(conflicts)],
        "slots_without_count": len(without),
        "slots_without_count_names": [without[k] for k in sorted(without)],
        "segments_agree": sum(v["agree"] for v in segments.values()),
        "segments_disagree": sum(v["disagree"] for v in segments.values()),
        "segments_unscored": sum(v["unscored"] for v in segments.values()),
        "segments_by_slot": {k: segments[k] for k in sorted(segments)
                             if segments[k]["half_samples"]}})
    casts = [lab for lab in labelled if lab["transition"] == "cast"]
    values.update({"labels": len(labelled), "labels_cast": len(casts),
                   "labels_cast_held_before": sum(bool(lab["held_before"]) for lab in casts),
                   "labels_by_transition": dict(sorted(Counter(
                       str(lab["transition"]) for lab in labelled).items()))})
    if casts:
        values["a1_held_fraction"] = round(values["labels_cast_held_before"] / len(casts), 4)
    values["a1_misses"] = [f"{lab['key']}:{lab['agent']}:level={lab['before_level']}"
                           f":held={lab['before_held_level']}:fill={lab['before_fill']}"
                           for lab in casts if not lab["held_before"]]
    return values


def cmd_ability_shapes(args) -> int:
    """The drawn minimap shape after each of the player's casts of an ability
    with a known form, from stored crops (`ability_shapes`). Decodes no video."""
    from . import ability_shapes
    from .ability_timeline import player_tray_casts, stored_gate_inputs
    from .lineup import abilities_for, load_lineup
    from .adjudication.identity import player_identity
    from .roi_cache import RoiCache
    from .version import PLAYER_CAST_VERSION, TRAY_VERSION

    store = Store(args.store)
    for sid in _sessions_arg(store, args):
        drops = store.read_events("tray_drop", sid)
        if not drops or drops[0].get("tray_version") != TRAY_VERSION:
            print(f"{sid}: no current tray drops -- run `reticle tray {sid}` first")
            continue
        lu = load_lineup(sid, store.root) or {}
        agent = player_identity(lu, sid)["agent"]
        if agent is None:
            print(f"{sid}: the arbiter names no player agent -- skipped")
            continue
        kit = abilities_for(agent, store.root)
        man = store.read_manifest(sid)
        # The gate decides afresh from the stored drops, as `ult-cast` asks it,
        # so a gate change needs no reread of the tray's crops.
        table = store.read_rounds(sid, _date_of(man))
        if table is None:
            print(f"{sid}: no rounds table, so every tray drop is `no_rounds` -- skipped")
            continue
        rounds = table.to_pylist()
        gate, _stamps = stored_gate_inputs(store, sid, _date_of(man), rounds, agent)
        casts = [d for d in player_tray_casts(
                     [d for d in drops if d.get("kind") == "drop"],
                     gate["phase_of"], rounds, gate["player_deaths_ms"], agent=gate["agent"],
                     second_lives_ms=gate["second_lives_ms"], revives_ms=gate["revives_ms"],
                     report_deaths=gate["report_deaths"], kit_changes_ms=gate["kit_changes_ms"],
                     kit_returns_ms=gate["kit_returns_ms"], menu_at=gate["menu_at"])
                 if d["player_cast"] and kit.get(d["slot"]) in ability_shapes.SHAPES]
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
        if cache is None:
            print(f"{sid}: no minimap crop cache ({why}) -- skipped")
            continue
        x0, y0, x1, y1 = cache.rect_of("minimap")
        support = geometry.footprint(sid, store.root, dilate=ability_shapes.SUPPORT_DILATE,
                                     shape=(y1 - y0, x1 - x0))
        if support is None:
            print(f"{sid}: no art footprint for this map -- no beam is checked against the map")
        mm = store.read_minimap(sid, _date_of(man))
        mm_version = (mm.schema.metadata or {}).get(b"minimap_version", b"").decode() or None
        mt = np.asarray(mm.column("t_ms").to_pylist(), float)
        sx, sy = mm.column("self_x").to_pylist(), mm.column("self_y").to_pylist()

        def seed_at(t):
            return ability_shapes.seed_from_track(mt, sx, sy, t)

        common = {"session_id": sid, "agent": agent, "tray_version": TRAY_VERSION,
                  "player_cast_version": PLAYER_CAST_VERSION,
                  "seed_source": "stored self position", "minimap_version": mm_version,
                  "seed_tol_ms": ability_shapes.SEED_TOL_MS}
        rows, found = [], Counter()
        for c in casts:
            ability = kit[c["slot"]]
            times = _cache_grid(cache.t_ms, c["t_ms"], c["t_ms"] + args.window * 1000.0, args.step)
            got = {float(smp.t_ms): smp.frame[y0:y1, x0:x1]
                   for smp in cache.samples(times, rois=["minimap"])}
            for t in times:
                seed = seed_at(t)
                row = ability_shapes.fit_shape(got.get(t), ability, seed, support)
                rows.append({**common, "kind": "shape", "cast_t_ms": c["t_ms"],
                             "slot": c["slot"], "t_ms": t, "seed": seed, **row})
                found[(ability, row["found"])] += 1
        out_rows = [{**common, "kind": "coverage", "casts": len(casts),
                     "ability_shape_version": ability_shapes.ABILITY_SHAPE_VERSION,
                     "observations": len(rows),
                     "found": {f"{a}:{f}": n for (a, f), n in sorted(found.items(), key=str)}}]
        out = store.write_events("ability_shape", sid, out_rows + rows)
        print(f"{sid}: {agent}, {len(casts)} casts with a shape model, {len(rows)} crops; "
              f"{out_rows[0]['found']} -> {out}")
    return 0


def cmd_ult_lines(args) -> int:
    """Peaks of the official ultimate voice lines in each capture's audio
    (`ult_lines`). Decodes the audio stream only, in memory; no video frame."""
    from . import ult_lines
    from .version import ULT_LINE_VERSION

    store = Store(args.store)
    voice = store.root / ult_lines.VOICE_DIR
    declared = ult_lines.load_manifest()
    if args.check_manifest:
        want = {e["name"]: e for e in declared["templates"]}
        got = {e["name"]: e for e in ult_lines.manifest_from_assets(voice)}
        differ = sorted(n for n in set(want) | set(got) if want.get(n) != got.get(n))
        for n in differ:
            print(f"  {n}: declared {want.get(n)}, the assets hold {got.get(n)}")
        print(f"{len(want)} templates declared ({declared['key']}); "
              f"{len(differ)} differ from {voice}")
        return 1 if differ else 0
    if not args.all and not args.session:
        raise SystemExit("name a session or pass --all")
    xp = ult_lines.array_module()
    templates = ult_lines.build_templates(voice, declared["templates"], xp=xp)
    print(f"{len(templates)} templates ({declared['key']}), longest "
          f"{max(t['span_s'] for t in templates):.2f} s, on {xp.__name__}")
    for sid in _sessions_arg(store, args):
        man = store.read_manifest(sid)
        src = man["source"]
        head = (store.read_events("ult_line", sid) or [{}])[0]
        if (not args.force and head.get("ult_line_version") == ULT_LINE_VERSION
                and head.get("content_key") == src["content_key"]
                and head.get("templates_key") == declared["key"] and not head.get("reason")):
            print(f"{sid}: current at {ULT_LINE_VERSION} -- pass --force to reread")
            continue
        media = Path(src["path"])
        if not media.is_file():
            print(f"{sid}: source media has moved: {media} -- skipped, nothing written")
            continue
        try:
            info, peaks = ult_lines.read_capture(str(media), templates, xp=xp)
        except (IndexError, ValueError) as e:
            reason = "no_audio_stream" if isinstance(e, IndexError) else str(e)
            out = store.write_events("ult_line", sid, [{
                "session_id": sid, "ult_line_version": ULT_LINE_VERSION,
                "content_key": src["content_key"], "kind": "coverage", "templates": len(templates),
                "templates_key": declared["key"], "peaks": 0, "reason": reason}])
            print(f"{sid}: refused ({reason}) -> {out}")
            continue
        rows = ult_lines.observations(sid, src["content_key"], ULT_LINE_VERSION, templates,
                                      declared["key"], info, peaks)
        out = store.write_events("ult_line", sid, rows)
        print(f"{sid}: {len(rows) - 1} peaks over {info['n_frames'] * ult_lines.HOP / 60:.1f} min "
              f"(decode {info['decode_s']} s, score {info['score_s']} s, {info['backend']}) -> {out}")
    return 0


def _ult_tray_drops(store, sid: str, date: str, rounds: list[dict], agent: str | None):
    """(the X drops with the verdict `ability_timeline.player_tray_casts` gives
    each, or None; the reason for None; the input stamps) for `ult-cast`."""
    from .ability_timeline import stored_gate_inputs
    from .adjudication.ult_cast import player_x_drops
    from .version import TRAY_VERSION

    drops = store.read_events("tray_drop", sid)
    if not drops:
        return None, "no_tray_drops", {}
    if drops[0].get("tray_version") != TRAY_VERSION:
        return None, "tray_drops_stale", {"tray_drop": drops[0].get("tray_version")}
    gate, stamps = stored_gate_inputs(store, sid, date, rounds, agent)
    return player_x_drops(drops, rounds=rounds, **gate), None, {"tray_drop": TRAY_VERSION,
                                                                **stamps}


def cmd_ult_cast(args) -> int:
    """Ultimate casts, their side and their round from stored voice-line peaks,
    the lineup and the rounds table (`adjudication.ult_cast`), with own lines
    bound to the player's X casts from the stored tray drops. Decodes nothing."""
    from .adjudication.ult_cast import THRESHOLD, adjudicate, player_agent
    from .lineup import load_lineup
    from .version import PLAYER_CAST_VERSION, TRAY_VERSION, ULT_CAST_VERSION, ULT_LINE_VERSION

    store = Store(args.store)
    pooled, sessions, stamps, timing = Counter(), [], set(), {"decode_s": [], "score_s": []}
    missed_best, witnessed_scores, missed_detail = [], [], {}
    for sid in _sessions_arg(store, args):
        peaks = store.read_events("ult_line", sid)
        if not peaks or peaks[0].get("ult_line_version") != ULT_LINE_VERSION:
            if not args.all:
                print(f"{sid}: no current ult_line peaks -- run `reticle ult-lines {sid}` first")
            continue
        man = store.read_manifest(sid)
        table = store.read_rounds(sid, _date_of(man))
        rounds = table.to_pylist() if table is not None else []
        round_version = (((table.schema.metadata or {}).get(b"round_version", b"").decode()
                          or "unstamped") if table is not None else None)
        lineup = load_lineup(sid, store.root)
        tray_drops, tray_reason, tray_inputs = _ult_tray_drops(
            store, sid, _date_of(man), rounds, player_agent(lineup, sid))
        res = adjudicate(sid, peaks, lineup, rounds, round_version,
                         tray_drops=tray_drops, tray_reason=tray_reason, tray_inputs=tray_inputs)
        out = store.write_events("ult_cast", sid, res["rows"])
        store.write_events("ult_cast_identity", sid, res["events"])
        cov = res["rows"][0]
        sessions.append(sid)
        stamps.add(peaks[0].get("templates_key"))
        pooled.update({"sessions_with_lineup": int(cov["lineup"]), "peaks": cov["peaks"],
                       "selected": cov["selected"], "casts": cov["casts"],
                       "refusals": cov["refusals"], "player_casts": cov["by_class"]["own"],
                       **{f"class_{c}": n for c, n in cov["by_class"].items()}})
        pooled.update(Counter(f"named_{r['side']}" for r in res["rows"]
                              if r.get("kind") == "cast" and r["agent"]))
        if cov["lineup"]:
            pooled.update({"lineup_selected": cov["selected"],
                           **{f"lineup_class_{c}": n for c, n in cov["by_class"].items()}})
        if cov["tray"]["bound"]:
            # Own lines against the tray, pooled and by the player's agent.
            a = cov["player_agent"]
            got = {"x_casts": cov["tray"]["player_x_casts"] - cov["tray"]["casts_outside_round"],
                   "own_witnessed": cov["own_witnessed"],
                   "own_unwitnessed": cov["own_unwitnessed"],
                   "missed_lines": cov["missed_lines"],
                   "missed_with_peak": cov["missed_with_peak"]}
            pooled.update({"tray_sessions": 1, "x_casts_outside_round":
                           cov["tray"]["casts_outside_round"], **got,
                           **{f"{k}_{a}": n for k, n in got.items()},
                           **{f"own_beside_refused_{why.replace(':', '_')}": n
                              for why, n in cov["own_beside_refused_drop"].items()},
                           **{f"own_beside_refused_{why.replace(':', '_')}_{a}": n
                              for why, n in cov["own_beside_refused_drop"].items()}})
            missed_best += [r["best_peak"]["score"] for r in res["rows"]
                            if r.get("kind") == "missed_line" and r["best_peak"]]
            # Each missed cast: the drop's X fill before it, and the best own peak.
            for r in res["rows"]:
                if r.get("kind") == "missed_line":
                    key = f"missed_{sid}_{int(r['cast_t_ms'] // 1000)}"
                    missed_detail[f"{key}_from"] = r["tray"]["from"]
                    if r["best_peak"]:
                        missed_detail[f"{key}_best"] = r["best_peak"]["score"]
                        missed_detail[f"{key}_dt_s"] = r["best_peak"]["dt_s"]
            witnessed_scores += [r["score"] for r in res["rows"]
                                 if r.get("kind") == "cast" and r.get("tray_witness")]
        else:
            pooled.update({f"tray_unbound_{cov['tray']['reason']}": 1})
        for k, got in timing.items():
            if peaks[0].get(k) is not None:
                got.append(float(peaks[0][k]))
        print(f"{sid}: {cov['selected']} of {cov['peaks']} peaks selected; {cov['by_class']}; "
              f"player {cov['player_agent']}; tray "
              + (f"{cov['own_witnessed']} own witnessed, {cov['own_unwitnessed']} not, "
                 f"{cov['missed_lines']} missed ({cov['missed_with_peak']} with a peak)"
                 if cov["tray"]["bound"] else f"unbound ({cov['tray']['reason']})")
              + f" -> {out}")
    if args.record and sessions:
        from . import metrics
        values = {"sessions": len(sessions), **dict(sorted(pooled.items()))}
        # What the stored reads took, from each session's ult_line coverage row.
        for k, got in timing.items():
            if got:
                values.update({f"{k}_min": min(got), f"{k}_median": float(np.median(got)),
                               f"{k}_max": max(got)})
        # The share of in-round X casts with an own line, and the best own-template
        # peak under each missed cast against the witnessed own lines' scores.
        if values.get("x_casts"):
            values["x_casts_with_line_fraction"] = round(
                1.0 - values["missed_lines"] / values["x_casts"], 3)
        values.update(missed_detail)
        for name, got in (("missed_best", missed_best), ("witnessed_score", witnessed_scores)):
            if got:
                q = np.quantile(got, [0.0, 0.25, 0.5, 0.75, 1.0])
                values.update({f"{name}_{k}": round(float(x), 4) for k, x in
                               zip(("min", "q25", "median", "q75", "max"), q)})
        metrics.record(tool="ult_lines", part="ult-cast",
                       session=args.session if not args.all else "all-sessions",
                       values=values,
                       deps={"ult_line_version": ULT_LINE_VERSION,
                             "ult_cast_version": ULT_CAST_VERSION,
                             "tray_version": TRAY_VERSION,
                             "player_cast_version": PLAYER_CAST_VERSION,
                             "threshold": THRESHOLD,
                             "templates_key": sorted(k for k in stamps if k)},
                       context={"session_ids": sessions})
        print(f"recorded ult_lines/ult-cast: {values}")
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


def cmd_ally_portrait_refs(args) -> int:
    """Bake the minimap ally-portrait references from the stored art and calibration."""
    from . import ally_portrait
    from .minimap import portrait_key
    store = Store(args.store)
    table = ally_portrait.build_references(store.root, portrait_key)
    print(f"{table['version']}: {len(table['agents'])} agents, calibration "
          f"{table['calibration']['version']} ({table['calibration']['sha']})")
    return 0


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

    s = sub.add_parser("usage", help="VOD scan timings, completed and failed, by session and reader")
    s.add_argument("session", nargs="?", help="filter by VOD session id")
    s.add_argument("--limit", type=int, default=5, help="latest records (default 5)")
    s.add_argument("--json", action="store_true", help="show full timing buckets")
    s.set_defaults(func=cmd_usage)

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
                   help=f"ally icon rate (default {ALLY_DESCRIPTOR_HZ:g}, the minimap "
                        "cache's). A lower rate reads the cached frame nearest each decode "
                        "instant, an opt-in: 2 Hz scored worse on segment identity "
                        "(docs/ALLY_ICON_RESAMPLE.md)")
    s.add_argument("--only", nargs="+",
                   choices=("hud", "minimap", "ping", "roster", "scoreboard",
                            "ally_icon", "minimap_dark", "combat_report", "roi_cache"),
                   help="run only these readers through the shared pass; roster-only needs no minimap geometry")
    s.add_argument("--report-hz", type=float, default=1.0,
                   help="combat report rate, whole capture (default 1)")
    s.add_argument("--dark-hz", type=float, default=4.0,
                   help="grey dark minimap floor rate for smokes (default 4)")
    s.add_argument("--no-roster", dest="roster", action="store_false",
                   help="skip the roster alive-count reader (it rides this pass free)")
    s.set_defaults(roster=True)
    s.add_argument("--no-scoreboard", dest="scoreboard", action="store_false",
                   help="skip context-free Tab-scoreboard rows and credit observations")
    s.set_defaults(scoreboard=True)
    s.add_argument("--from", dest="frames_from", default="auto",
                   choices=("auto", "cache", "video"),
                   help="auto (default): feed the pass from the ROI crop cache when every "
                        "reader in it reads only cached ROIs and the cache holds its frames "
                        "-- a span reader over a round cache reads the rounds only, as with "
                        "cache, when the cache holds every live round -- else decode; "
                        "cache: refuse to decode; video: always decode")
    s.add_argument("--cache-roi", choices=("killfeed", "hud", "minimap", "scoreboard"),
                   help="also store lossless crops of this ROI at the HUD rate, for "
                        "`reticle trial --from cache`; `--only roi_cache` stores only them. "
                        "scoreboard: the scoreboard reader's region, at its frames within "
                        "one sample of a stored strip sample that reads the board present "
                        "or the band unreadable")
    s.add_argument("--cache-hz", type=float, default=None,
                   help="rate of the ROI crops (default: the HUD rate)")
    s.add_argument("--cache-live", action="store_true",
                   help="store the crops over rounds only, from just before each "
                        "barrier drop to the next round's start (gametime)")
    s.add_argument("--pipeline", choices=("serial", "staged"), default="serial",
                   help="serial (default): every reader in turn per frame; staged: each "
                        "reader on its own thread behind a FIFO (reticle/pipeline.py)")
    s.add_argument("--workers", type=int, default=None,
                   help="staged: feeds that run at once (default 1); 0 runs inline")
    s.add_argument("--shard", action="append", default=[], metavar="NAME=N",
                   help="staged: split a reader that declares `shardable` N ways")
    s.add_argument("--cv-threads", type=int, default=None,
                   help="OpenCV threads for the pass (default: serial keeps OpenCV's pool, "
                        "staged uses 1)")
    s.add_argument("--check", action="store_true",
                   help="run the serial pass and this one into two temporary stores and "
                        "compare every file; writes nothing into the store")
    s.add_argument("--check-dir", default=None,
                   help="an empty directory for --check's two stores (default: a new "
                        "temporary directory, kept)")
    s.add_argument("--until", type=float, default=None, metavar="SECONDS",
                   help="offer only frames observed before SECONDS on both paths; a video "
                        "decode stops there. Needs --check and --check-dir, since a prefix's "
                        "streams are not the whole capture's")
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

    s = sub.add_parser("verify", help="check HUD reads against domain invariants, "
                                      "or run a verification tier")
    s.add_argument("session", nargs="?")
    s.add_argument("--tier", choices=("fast",), default=None,
                   help="known answers on a few fixed sessions from storage and the crop "
                        "cache, no decode: the default sanity check")
    s.add_argument("--only", default=None, help="with --tier, run the one check with this id")
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

    s = sub.add_parser("strip", help="the scoreboard's round-history strip at every cached frame, "
                                     "from stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.set_defaults(func=cmd_strip)

    s = sub.add_parser("openings", help="scoreboard openings from the slab test and the strip "
                                        "together, from storage (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.set_defaults(func=cmd_openings)

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

    s = sub.add_parser("combat-report", help="combat report panels and per-round counts from stored rows (no video)")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_combat_report)

    s = sub.add_parser("deaths", help="death verdicts per killfeed entry from stored data (no video)")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_deaths)

    s = sub.add_parser("plan", help="stale stored streams and the least work that refreshes them")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("trial", help="rerun one reader on stored windows and diff it (writes nothing)")
    s.add_argument("session", nargs="?")
    s.add_argument("--reader", default="killfeed",
                   choices=("killfeed", "hud", "scoreboard", "ally_icon"))
    s.add_argument("--from", dest="source", default="cache", choices=("cache", "video"),
                   help="ROI crop cache (no decode) or seeks into the capture")
    s.add_argument("--windows", default="occupied", choices=("occupied", "all"),
                   help="frames near a stored killfeed entry (scoreboard: inside the strip "
                        "gate; ally_icon: widget drawn), or the whole timeline")
    s.add_argument("--pad-ms", type=float, default=2000.0)
    s.add_argument("--between", type=float, nargs=2, default=None, metavar=("T0", "T1"),
                   help="only frames between T0 and T1 seconds, such as one round")
    s.set_defaults(func=cmd_trial)

    s = sub.add_parser("reliability", help="identity channel reliability per agent (no video)")
    s.add_argument("--top", type=int, default=12)
    s.set_defaults(func=cmd_reliability)

    s = sub.add_parser("smokes", help="smoke tracks and who cast them, from stored minimap_dark rows (no video)")
    s.add_argument("session", nargs="?")
    s.set_defaults(func=cmd_smokes)

    s = sub.add_parser("menu", help="whether the game's menu covers the HUD, from stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--step", type=float, default=0.5,
                   help="tray-crop sampling interval (default 0.5 s, the tray's)")
    s.set_defaults(func=cmd_menu)

    s = sub.add_parser("tray", help="the tray's charge drops and the player's casts, from stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--step", type=float, default=0.5, help="tray sampling interval (default 0.5 s)")
    s.set_defaults(func=cmd_tray)

    s = sub.add_parser("self-icon",
                       help="the minimap self icon's portrait scored against the agents' art, "
                            "from stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session with a stored lineup")
    s.add_argument("--step", type=float, default=1.0, help="sampling interval (default 1.0 s)")
    s.set_defaults(func=cmd_self_icon)

    s = sub.add_parser("spike",
                       help="the spike's minimap glyph and roster marker from stored crops, "
                            "and its carrier cross-checked (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--step", type=float, default=1.0, help="sampling interval (default 1.0 s)")
    s.add_argument("--from-store", action="store_true",
                   help="rerun only the carrier cross-check from stored `spike` rows")
    s.set_defaults(func=cmd_spike)

    s = sub.add_parser("widget-fit",
                       help="where the session draws its minimap widget against the baked "
                            "static, from stored crops (no video)")
    s.add_argument("session")
    s.add_argument("--frames", type=int, default=24, help="cached frames to fit (default 24)")
    s.add_argument("--write", action="store_true",
                   help="store a non-identity placement on the manifest and tag the session")
    s.set_defaults(func=cmd_widget_fit)

    s = sub.add_parser("tray-kit",
                       help="whose kit the tray shows, from its slot icons in stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--step", type=float, default=0.5, help="sampling interval (default 0.5 s)")
    s.add_argument("--record", action="store_true",
                   help="record each session's numbers in notes/metrics.jsonl")
    s.add_argument("--at", type=float, nargs="*", default=[],
                   help="instants (s) whose reading --record stores")
    s.set_defaults(func=cmd_tray_kit)

    s = sub.add_parser("ability-state",
                       help="the player's kit as a state per slot, from stored drops and crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--record", action="store_true",
                   help="score the tray-cast labels and record the numbers in notes/metrics.jsonl")
    s.set_defaults(func=cmd_ability_state)

    s = sub.add_parser("ability-shapes",
                       help="the drawn minimap shape after the player's casts, from stored crops (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--window", type=float, default=6.0, help="seconds after each cast (default 6)")
    s.add_argument("--step", type=float, default=0.5, help="sampling interval (default 0.5 s)")
    s.set_defaults(func=cmd_ability_shapes)

    s = sub.add_parser("ult-lines",
                       help="peaks of the official ultimate voice lines in the capture's audio (no video)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session")
    s.add_argument("--force", action="store_true", help="reread a session whose peaks are current")
    s.add_argument("--check-manifest", action="store_true",
                   help="compare the declared templates with the assets, and read nothing")
    s.set_defaults(func=cmd_ult_lines)

    s = sub.add_parser("ult-cast",
                       help="ultimate casts, side and round from stored voice-line peaks (storage only)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session with current peaks")
    s.add_argument("--record", action="store_true", help="record the pooled counts in the metrics log")
    s.set_defaults(func=cmd_ult_cast)

    s = sub.add_parser("vision", help="store the team's adjudicated vision per frame "
                                      "(minimap crop cache; decodes no capture)")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true", help="every session with a minimap crop cache")
    s.add_argument("--at-candidates", action="store_true",
                   help="only the frames around each ability candidate's instant")
    s.add_argument("--warmup-ms", type=float, default=None,
                   help="cap the chain's history before each instant with "
                        "--at-candidates (default: from the last cache gap, which "
                        "reproduces the full run; a cap may not)")
    s.add_argument("--check", action="store_true",
                   help="write nothing; compare the computed frames with the stored product")
    s.set_defaults(func=cmd_vision)

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

    s = sub.add_parser("ally-portrait-refs", help="bake minimap ally-portrait "
                       "references rendered from the stored art")
    s.set_defaults(func=cmd_ally_portrait_refs)

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
