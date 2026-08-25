"""Reticle ingestion CLI.

    reticle synth   [--out PATH]              make a synthetic clip to test with
    reticle probe   VIDEO                     fingerprint + render ROI overlays
    reticle ingest  VIDEO                     decode -> L1 primitives -> parquet
    reticle segment SESSION|--all             recompute spans from stored L1
    reticle inspect [SESSION]                 what is in the store
    reticle frames  SESSION --every N         dump frames for eyeballing
    reticle hud     [SESSION]                 stage 02: read the scoreline
    reticle glyphs  VIDEO                     mine digit templates from footage
    reticle verify  [SESSION]                 check HUD reads against domain invariants
    reticle overlay [SESSION]                 render detections onto the video
    reticle kd      [SESSION]                 running K/D per round, to check against the scoreboard
    reticle board   [SESSION]                 read the Tab scoreboard and score our K/D against it
    reticle sql     "SELECT ..."              DuckDB over the store
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import time
from pathlib import Path

import numpy as np

from .decode import sample_frames
from .checks import KNOWN_KD, check_hud, player_events, track_entries
from .rounds import build_rounds, summarise
from .scoreboard import read_scoreboard
from .fingerprint import fingerprint
from .killfeed import (KillfeedRead, analyse_killfeed, killfeed_roi,
                       overlay_mask, read_killfeed)
from .overlay import OverlayContext, draw
from .ocr import (GLYPH_H, GLYPH_W, Templates, cluster_glyphs, crop_gray,
                  read_bottom_hud, read_scoreline, scoreline_roi, segment_glyphs)
from .primitives import PrimitiveExtractor
from .profiles import DEFAULT_PROFILE, MinimapMode, get_profile
from .segment import HUD_CHROME_ROIS, STATES, SegmentConfig, classify, segment
from .store import DEFAULT_STORE, Store
from .version import EXTRACTOR_VERSION, HUD_VERSION, SEGMENTER_VERSION


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
    for s in sessions:
        if s["session_id"].startswith(session):
            return s
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

    templates = Templates.load(profile.name)
    roi = scoreline_roi(profile)
    kf_roi = killfeed_roi(profile)
    w, h = int(src["width"]), int(src["height"])

    print(f"session    {sid}  ({src['filename']})")
    print(f"profile    {profile.name}  ({HUD_VERSION}, {len(templates)} glyph templates)")
    print(f"roi        scoreline {roi.pixels(w, h)}  + hud_hp, hud_ammo")
    print(f"sampling   {args.hz:g} Hz")

    # Calibrate the killfeed overlay mask before decoding. Which optional HUD
    # readouts are switched on is a per-player choice, so the mask is measured
    # from this capture rather than assumed.
    kf_mask = None
    if kf_roi is not None:
        cap = cv2.VideoCapture(str(media))
        cal = []
        try:
            step = max(1, int((src["duration_ms"] or 0) / 40))
            for ms in range(0, int(src["duration_ms"] or 0), step):
                cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                ok, fr = cap.read()
                if ok:
                    cal.append(fr)
        finally:
            cap.release()
        if cal:
            kf_mask = overlay_mask(cal, kf_roi, w, h)
            print(f"killfeed   overlay mask from {len(cal)} frames, "
                  f"{(~kf_mask).mean() * 100:.1f}% of the ROI masked out")

    rows: list[dict] = []
    t0 = time.perf_counter()
    last = t0
    for smp in sample_frames(str(media), args.hz, src["fps"], args.max_frames):
        r = read_scoreline(crop_gray(smp.frame, roi, w, h), templates,
                          args.min_confidence, args.min_margin)
        b = read_bottom_hud(smp.frame, profile, templates, w, h,
                            args.min_confidence, args.min_margin)
        kf = (read_killfeed(smp.frame, kf_roi, w, h, kf_mask, profile.name)
              if kf_roi is not None else KillfeedRead(0, (), False, False))
        rows.append({
            "frame_idx": smp.frame_idx,
            "t_ms": smp.t_ms,
            "clock_ms": r.clock_ms,
            "score_left": r.score_left,
            "score_right": r.score_right,
            "hp": b.hp,
            "shield": b.shield,
            "ammo_mag": b.ammo_mag,
            "ammo_reserve": b.ammo_reserve,
            "kf_entries": kf.entries,
            "kf_player_kill": kf.player_kill,
            "kf_player_death": kf.player_death,
            "kf_entry_mask": kf.entry_mask,
            "kf_kill_mask": kf.kill_mask,
            "kf_death_mask": kf.death_mask,
            "kf_unattributed": kf.unattributed,
            "kf_entry_wx": kf.entry_dividers,
            "kf_kill_wx": kf.kill_dividers,
            "kf_death_wx": kf.death_dividers,
            "confidence": r.confidence,
            "bottom_confidence": b.confidence,
            "n_glyphs": r.n_glyphs,
        })
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
    print("   at        board K/D/A    ours K/D    delta     rows")
    worst = None
    for grp in openings:
        # the frame of this opening with the most rows fully read
        t, sb = max(grp, key=lambda p: sum(1 for r in p[1].rows if r.complete))
        pl = sb.player
        got = sum(1 for r in sb.rows if r.complete)
        cell = f"{pl.kills}/{pl.deaths}/{pl.assists}"
        if tracked is None:
            print(f"  {_fmt_hms(t):>8s}  {cell:>12s}    {'-':>8s}    {'-':>6s}   {got}/10")
            continue
        ok = sum(1 for x in tracked[0] if x <= t)
        od = sum(1 for x in tracked[1] if x <= t)
        dk, dd = ok - pl.kills, od - pl.deaths
        flag = "" if (dk == 0 and dd == 0) else "  <-"
        if worst is None and (dk or dd):
            worst = t
        print(f"  {_fmt_hms(t):>8s}  {cell:>12s}    {ok:2d} / {od:2d}   "
              f"{dk:+d} / {dd:+d}   {got}/10{flag}")

    last = max(openings[-1], key=lambda p: sum(1 for r in p[1].rows if r.complete))[1]
    print("\nfull board at the last opening:")
    for r in last.rows:
        who = "  <- you" if r.is_player else ""
        print(f"   {r.team:5s}  {str(r.kills):>3s} / {str(r.deaths):>3s} / "
              f"{str(r.assists):>3s}{who}")
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

    ctx = OverlayContext(profile=profile, templates=templates, width=w, height=h,
                         kf_mask=kf_mask, min_confidence=args.min_confidence,
                         min_margin=args.min_margin, spans=spans)

    out = Path(args.out) if args.out else Path.cwd() / f"overlay_{sid}_{int(t_from)}ms.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    scale = args.scale
    size = (int(w * scale), int(h * scale))
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                             args.fps or args.hz, size)
    if not writer.isOpened():
        raise SystemExit(f"could not open {out} for writing")

    cap = cv2.VideoCapture(str(media))
    step_ms = 1000.0 / args.hz
    written = skipped = 0
    t0 = time.perf_counter()
    try:
        t = t_from
        while t < t_to:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
            ok, frame = cap.read()
            if not ok:
                break
            if args.entries_only and kf_roi is not None:
                # Skip frames with an empty feed: for debugging attribution, the
                # frames without an entry are the ones with nothing to look at.
                if not analyse_killfeed(frame, kf_roi, w, h, kf_mask, profile.name):
                    t += step_ms
                    skipped += 1
                    continue
            canvas = draw(frame, t, int(round(t / 1000.0 * fps)), ctx)
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
        won = [r["won"] for r in rs if r["won"] is not None]
        print(f"{sid:14s} {mp:8s} {len(rs):6d} {rs[0]['player_side']:>6s} "
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
    s.add_argument("--entries-only", action="store_true",
                   help="only render frames whose killfeed holds an entry")
    s.add_argument("--min-confidence", type=float, default=0.82)
    s.add_argument("--min-margin", type=float, default=0.05)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_overlay)

    s = sub.add_parser("rounds", help="stage 05: derive rounds and score win rates")
    s.add_argument("session", nargs="?")
    s.add_argument("--by-map", action="store_true", help="also split every fact by map")
    s.set_defaults(func=cmd_rounds)

    s = sub.add_parser("sql", help="run DuckDB over the store")
    s.add_argument("query", nargs="?"); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_sql)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
