"""Lossless crops of fixed HUD regions, stored so a reader can rerun without
decoding the capture.

A reader whose every pixel read falls inside a declared set of profile ROIs
(the killfeed reader inside `killfeed`; the HUD reader inside the score line,
bottom HUD and killfeed) can be fed from these crops: `RoiCache.sample`
pastes each stored crop into a black frame of the capture's size, so the
reader runs unchanged and sees the same pixels inside its ROIs. What it reads
outside them is black, which is why the check is equality of the reader's
output against a decoded run, not the assumption that it stays inside.

The player's decision (2026-09-25): a crop of a known reader ROI is not a copy
of the raw media; the rule against copying is about duplicating the capture.

A cache is keyed by session, set name (`CACHE_SETS`) and `ROI_CACHE_VERSION`,
and records the source content key, profile and rectangles; `RoiCache.load`
refuses a cache whose record disagrees with the session now, and serves a set
from any cache whose rectangles include it. Crops are PNG, so the pixels are
the decoder's, bit for bit.

**A 15 Hz set is stored as video, not PNG.** PNG compresses each frame alone,
so 15 Hz minimap crops over the corpus's live rounds measured about as large
as the corpus itself. FFV1 in `bgr0` through `ffmpeg` (`CODECS`) is lossless
-- 147 of 147 frames read back bit for bit through OpenCV, seeks included --
at a third of PNG's size; lossless x264 was larger, since the minimap changes
too much between frames for prediction to pay. Every FFV1 frame is a key
frame, so a seek lands on the frame asked for.

**The scoreboard set is gated on an opportunity.** Its one rectangle is not
a profile ROI but the region the Tab scoreboard reader reads
(`scoreboard.reader_roi`, frame x 535-1382 over the whole height at
1920x1080), placed by the strip's profile rectangle; a capture without that
rectangle has no such region, and the set refuses it. The writer rides the
scoreboard reader's own frames (whole capture, its rate) and keeps only
those inside the gate (`scoreboard_gate`): samples within
`SCOREBOARD_GATE_MARGIN` samples of one where the stored round-history strip
witness (`scoreboard_strip`) reads the board present or cannot read the band.
The gate never asks the slab test, whose opens are the reader's own outcome.
The record keeps the gate, its `rule` named (`gate_rule`), and
`RoiCache.refusal` says why a time outside it is not held. A gated cache
feeds a scan only under `--from cache` and only readers that declare
`reads_gate` (`cache_for`); the scoreboard set holds the frames `reticle
trial` reads.

**Rule `on`** (the player, 2026-10-05): the margin is 0, every strip
on-sample and no neighbour. Caches written at margin 1 are thinned from
themselves, no capture decoded (`thin_cache`, driven per session by
`prototypes/scoreboard_reads.py migrate`, which replaces a stored cache only
where its kept frames read back bit for bit and every consumer output equals
all frames'). A thinned record keeps the gate it was written under in
`thinned.gate_before`, so a dropped margin is refused as `thinned_out`, not
`outside_gate`.

**The tray takes no alive gate.** The tray (`hud_abilities`) is the second
rectangle of the `minimap` set, its own file, not part of the `hud` set:
[metric:tray_gate/projection@corpus-21#tray_gb=8.839] GB of the
[metric:tray_gate/projection@corpus-21#set_gb=31.559] GB set over the 21
matches (`prototypes/tray_gate.py`). A gate on the player alive in a round
(stored rounds and the death owner's verdicts, buy phase in, 1 s margins)
keeps [metric:tray_gate/projection@corpus-21#kept_share=0.6571] of its
samples and would save
[metric:tray_gate/projection@corpus-21#saved_gb_gate=3.031] GB, but the
samples it drops show the spectated teammate's kit, the evidence `tray_kit`
names teammates by: it would drop
[metric:tray_gate/projection@corpus-21#tray_kit_identity__row_dropped=238] of
[metric:tray_gate/projection@corpus-21#tray_kit_identity__row_total=332]
stored `tray_kit_identity` rows and
[metric:tray_gate/projection@corpus-21#tray_drop__drop_dropped=1478] of
[metric:tray_gate/projection@corpus-21#tray_drop__drop_total=3502] tray
drops. Every tray reader reads a 0.5 s grid of the cached times
(`grid_times`); that grid holds
[metric:tray_gate/projection@corpus-21#grid_samples=58887] of the
[metric:tray_gate/projection@corpus-21#tray_samples=394414] cached tray
samples, about [metric:tray_gate/projection@corpus-21#grid_tray_gb=1.32] GB
at the same bytes a frame, which a tray set at the readers' rate would hold
without losing a row they read.

**The tray is held on its readers' grid** (the player, 2026-10-05). Over
round spans the writer stores the tray (`GRID_ROIS`) only at the cached
times `grid_keep` names: `grid_times` at 0.5 s on each span, the rule
`reticle tray`, `tray-kit`, `menu` and `ability-state` read by. A streaming
`GridPicker` decides each frame as it arrives, and `finish` checks its picks
against `grid_keep` over every stored time, failing rather than storing
other frames. The minimap rectangle keeps every frame, and a whole-capture
cache (a demo) keeps every tray frame, since prototypes refine drops
between grid samples there. The record stamps each thinned ROI under
`thinned_rois` (`GRID_THIN_VERSION`, rule, step, frames kept, by whom).
A read that names the tray at a time the cache holds only the minimap
refuses: `refusal(t, rois)` says `thinned_out`, and `samples` raises
`ThinnedOut` rather than paste a black or neighbouring crop; asking no
ROIs asks them all. A pass reader declared on the set (`declare_set`) asks
the minimap alone (`cache_rois`). Stored caches are thinned from themselves
by `grid_thin_rect`, driven per session by `prototypes/tray_thin.py
migrate`, which replaces a stored tray file only where every kept frame
reads back bit for bit and every tray reader writes the same rows on the
thinned cache as on the full one, and refuses a session whose files are
open or being rewritten (`busy`). On a declared sample of three matches the
readers wrote [metric:tray_thin/migrate-check@sample-3#rows_compared=24360]
rows on each cache and [metric:tray_thin/migrate-check@sample-3#rows_differ=0]
differed; over the 21 matches the thinning frees
[metric:tray_thin/projection@corpus-58#gb_freed=7.519] of the
[metric:tray_thin/projection@corpus-58#gb_round=8.839] GB of tray files.

**The killfeed panel strip is gated on an entry.** Its one rectangle
(`killfeed_panel_rect`) is the strip immediately left of the killfeed ROI,
`KILLFEED_PANEL_BASE_PX` wide at 1080p (scaled by `killfeed.KillfeedScale`,
the killfeed's one transform), over the ROI's rows: the assist panel
[domain:killfeed/assist-panel] that the killfeed ROI's left edge cuts is
drawn there. It rides the HUD rate over the
whole capture, on the `hud` set's timeline, and keeps a sample only within
`KILLFEED_PANEL_GATE_MARGIN` samples of one where the stored
`killfeed_portrait` stream holds a killer row (`killfeed_panel_gate`): an
assist panel is drawn only beside an entry. The gate never asks the panel,
the outcome. Over the 21 matches an entry is on screen at
[metric:killfeed_panel/gate-projection#open_share=0.2642] of the HUD samples and
the gate keeps [metric:killfeed_panel/gate-projection#kept_share=0.3027] of them,
about [metric:killfeed_panel/gate-projection#mb_ffv1=301] MB as FFV1, from the
stored rows. `RoiCache.load_union` reads it with the `hud` set as one
cache, so a reader of the wider killfeed (`WIDE_ROIS`) gets both crops
pasted into one frame, and the gate's refusal at a time outside it.

**The combat report set keeps one frame per round.** The report does not
change within a round (the player, 2026-10-05), so the set holds, per round,
the one frame of its most complete panel that the owner of the panels'
rounds names (`adjudication.combat_report.round_frames`) from the stored
`combat_report` rows, the stored rounds and the player's deaths: the round
summary where it shows, else the frozen post-death panel, from inside a run
of frames that read the same. Its one rectangle is the region the combat
report reader reads (`combat_report.reader_roi`). The writer rides the
reader's own frames (whole capture, `--report-hz`), keeps the named frames
(`combat_report_gate`) and stores the timeline it was offered
(`TIMELINE_SETS`), so `scan --only combat_report --from cache` rereads each
kept panel with no video and stores every other frame as a refusal,
`thinned_out` (`unheld_frames`), never as a frame with no panel. A round
whose panels read different damage keeps one frame per read. The reread
stream gives each round its counts but not the death panel's timing, so
the consumers of that timing refuse it
(`adjudication.combat_report.thinned`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .decode import Sample

ROI_CACHE_VERSION = "roi-cache-0.1.0"

#: Named sets of profile ROIs, each the regions one pass's readers read.
CACHE_SETS = {
    "killfeed": ("killfeed",),
    # The HUD pass (`hud_reader.HudReader`), the roster that rides it, and the
    # screen centre. The spike graphic replaces the clock inside `scoreline`
    # [domain:hud/planted-spike-replaces-clock].
    "hud": ("scoreline", "hud_hp", "hud_ammo", "killfeed", "hud_roster", "hud_roster_enemy",
            "center"),
    # The minimap and the ability tray at the minimap rate, written over each
    # round from just before its barrier drop (`spans`): what was placed in the
    # buy phase is still drawn then [domain:rounds/buy-phase-barriers].
    "minimap": ("minimap", "hud_abilities"),
    # The Tab scoreboard reader's region (`DERIVED_ROIS`), at the frames the
    # strip gate keeps (`scoreboard_gate`).
    "scoreboard": ("scoreboard",),
    # The strip left of the killfeed ROI (`DERIVED_ROIS`), at the HUD samples
    # the killfeed entry gate keeps (`killfeed_panel_gate`).
    "killfeed_panel": ("killfeed_panel",),
    # The combat report reader's region (`DERIVED_ROIS`), one frame per round
    # (`combat_report_gate`).
    "combat_report": ("combat_report",),
}

#: Cache ROIs that are not profile ROIs: each is computed from the profile
#: and the frame size by the reader that owns the region.
DERIVED_ROIS = ("scoreboard", "killfeed_panel", "combat_report")

#: Regions wider than one stored set, read through `RoiCache.load_union`:
#: each is the bounding box of ROIs held by the sets named with it.
WIDE_ROIS = {"killfeed_wide": (("hud", "killfeed_panel"), ("killfeed_panel", "killfeed"))}

#: The killfeed panel strip's width at 1080p. 637 deaths over the 21 matches
#: had their assist panel cut by the killfeed ROI's left edge; the widest
#: credited panel ran 143 px past it (assist round 2, 2026-10-04).
KILLFEED_PANEL_BASE_PX = 143
#: Samples either side of a sample with a killfeed entry that open the gate.
KILLFEED_PANEL_GATE_MARGIN = 1
#: The killfeed_portrait roles whose rows mark an entry on screen.
KILLFEED_PANEL_GATE_ROLES = ("killer",)

#: Samples either side of a strip sample that opens the scoreboard gate. The
#: player chose rule `on` (2026-10-05): every on-sample and no margin. Over
#: the held half of the 21 matches the margin-1 caches held
#: [metric:scoreboard_reads/posthoc-on@held-half#cache_frames=24206] frames and
#: rule `on` keeps [metric:scoreboard_reads/posthoc-on@held-half#frames=18049]
#: (`prototypes/scoreboard_reads.py`, `posthoc`).
SCOREBOARD_GATE_MARGIN = 0
#: The name a gate record carries for the frames it keeps (`gate_rule`).
SCOREBOARD_GATE_RULE = "on"
#: The strip verdicts that open the gate: the board is seen, or the band is
#: too dark for the witness to say it is not there.
SCOREBOARD_GATE_VERDICTS = ("present", "unreadable")

#: The longest forward skip in an FFV1 cache that `samples` grabs through
#: rather than seeks. Measured 2026-09-28 on c40d950031bb's minimap cache: a
#: seek cost 38 ms a sample and a sequential read 5.7 ms a frame.
GRAB_MAX = 8

#: How each set's crops are stored: "png" per crop, or "ffv1" video per rect.
#: The scoreboard region is FFV1 for size alone: over one decoded minute of
#: a06f04a0059f its crops (848x1080) take
#: [metric:scoreboard/cache-window@a06f04a0059f#kb_per_frame_ffv1=345.0] kB a frame against
#: [metric:scoreboard/cache-window@a06f04a0059f#kb_per_frame_png=857.0] as PNG.
#: The killfeed panel strip is FFV1 for size too: over two decoded minutes
#: of 043bafca271a its gated crops (143x265) take
#: [metric:killfeed_panel/cache-window@043bafca271a#kb_per_sample_ffv1=11.3] kB a sample
#: against [metric:killfeed_panel/cache-window@043bafca271a#kb_per_sample_png=27.4] as PNG,
#: and every one read back bit for bit, irregular seeks included
#: ([metric:killfeed_panel/cache-window@043bafca271a#seek_bit_equal_ffv1=52] of 52).
CODECS = {"minimap": "ffv1", "scoreboard": "ffv1", "killfeed_panel": "ffv1",
          "combat_report": "ffv1"}

#: Gated sets that store the timeline their writer was offered
#: (`{sid}.offered.npy`), so a reader fed from them refuses each frame the
#: gate dropped by its time (`unheld_frames`).
TIMELINE_SETS = ("combat_report",)

#: Profile ROIs a set stores only on its readers' grid, with the grid's step
#: in seconds: the ability tray, which `reticle tray`, `tray-kit`, `menu`
#: and `ability-state` read at 0.5 s (`grid_times` on each cache span), while
#: the minimap beside it keeps the set's rate. Only a cache written over
#: round spans thins (`grid_keep`); a whole-capture cache (a demo) keeps
#: every frame.
GRID_ROIS = {"minimap": {"hud_abilities": 0.5}}
#: The stamp a grid-thinned ROI carries in its record (`thinned_rois`).
GRID_THIN_VERSION = "roi-grid-thin-0.1.0"


class ThinnedOut(ValueError):
    """A reader named a grid-thinned ROI at a time the cache holds other
    crops for but not that one (`GRID_ROIS`): the frame was dropped, never
    replaced by a neighbour. `reason` is `thinned_out`."""

    reason = "thinned_out"

    def __init__(self, roi: str, t_ms: float, step_s: float | None):
        super().__init__(f"thinned_out: the cache holds {roi} only on its {step_s} s grid, "
                         f"not at {float(t_ms)} ms")
        self.roi, self.t_ms = roi, float(t_ms)


def ffmpeg_path() -> str:
    """The ffmpeg executable: on PATH, or where winget installs it."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import os
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    for p in sorted(base.glob("**/ffmpeg.exe")):
        return str(p)
    raise SystemExit("ffmpeg not found: install it (winget install Gyan.FFmpeg)")


def ffv1_command(ff: str, w: int, h: int, hz: float, out: Path,
                 threads: int | None = None) -> list[str]:
    """The ffmpeg command that writes one rect's FFV1 cache video from
    `bgr24` frames piped on stdin: the writer's, and `thin_cache`'s with
    `threads` 1."""
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{int(w)}x{int(h)}", "-r", str(hz), "-i", "-"]
    if threads is not None:
        cmd += ["-threads", str(int(threads))]
    return cmd + ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0", str(out)]


def roi_rects(name: str, profile, wh: tuple[int, int],
              manifest: dict | None = None) -> list[list[int]]:
    """The pixel rectangles (x0, y0, x1, y1) of a cache set, in set order.

    A `manifest` whose widget placement names a capture box
    (`widget_frame.capture_box`) replaces the minimap rectangle with it: that
    session draws its widget outside the profile's ROI, and only it does."""
    if name not in CACHE_SETS:
        raise ValueError(f"no cacheable ROI set named {name!r}; have {sorted(CACHE_SETS)}")
    by = {r.name: r for r in profile.rois}
    missing = [r for r in CACHE_SETS[name] if r not in by and r not in DERIVED_ROIS]
    if missing:
        raise ValueError(f"profile {profile.name} lacks ROIs {missing} for set {name!r}")
    rects = [derived_rect(r, profile, wh) if r in DERIVED_ROIS
             else [int(v) for v in by[r].pixels(*wh)] for r in CACHE_SETS[name]]
    if manifest is not None and "minimap" in CACHE_SETS[name]:
        from .widget_frame import capture_box
        box = capture_box(manifest)
        if box is not None:
            rects[CACHE_SETS[name].index("minimap")] = box
    return rects


def derived_rect(roi: str, profile, wh: tuple[int, int]) -> list[int]:
    """The pixel rectangle of a `DERIVED_ROIS` entry, from the reader that
    owns the region; ValueError where the capture places none."""
    if roi == "killfeed_panel":
        return killfeed_panel_rect(profile, wh)
    if roi == "combat_report":
        from .combat_report import reader_roi as report_roi
        return report_roi(wh)
    if roi != "scoreboard":
        raise ValueError(f"no derived ROI named {roi!r}; have {list(DERIVED_ROIS)}")
    from .scoreboard import reader_roi, strip_rect
    rect = strip_rect(profile.name, int(wh[0]), int(wh[1]))
    if rect is None:
        raise ValueError(f"profile {profile.name} at {wh[0]}x{wh[1]} gives no strip rectangle, "
                         f"so the scoreboard reader reads the whole frame and no region holds it")
    return [int(v) for v in reader_roi(rect, int(wh[1]))]


def killfeed_panel_rect(profile, wh: tuple[int, int]) -> list[int]:
    """The strip immediately left of the profile's killfeed ROI, over its
    rows: `KILLFEED_PANEL_BASE_PX` at 1080p through the killfeed's one scale
    (`KillfeedScale.for_capture`), cut at the frame's left edge."""
    from .killfeed import KillfeedScale, killfeed_roi
    roi = killfeed_roi(profile)
    if roi is None:
        raise ValueError(f"profile {profile.name} has no killfeed ROI to place the panel strip by")
    x0, y0, _x1, y1 = (int(v) for v in roi.pixels(int(wh[0]), int(wh[1])))
    w = KillfeedScale.for_capture(int(wh[0]), int(wh[1])).n(KILLFEED_PANEL_BASE_PX)
    if x0 <= 0 or w <= 0:
        raise ValueError(f"profile {profile.name} at {wh[0]}x{wh[1]} puts the killfeed ROI at "
                         f"the frame's left edge; no strip lies left of it")
    return [max(0, x0 - w), y0, x0, y1]


def killfeed_panel_gate(portrait_rows: list[dict], hz: float,
                        margin: int = KILLFEED_PANEL_GATE_MARGIN
                        ) -> tuple[dict | None, str | None]:
    """The killfeed panel set's gate from a session's stored
    `killfeed_portrait` rows, or None and why there is none.

    The gate is an opportunity: an entry on screen, which the killfeed
    reader's killer rows (`KILLFEED_PANEL_GATE_ROLES`, refused rows
    included: a refused description is still an entry) mark at their
    sample. Each such time opens the span `margin` samples of the cache's
    rate either side, plus half a sample, so on the HUD grid it holds exactly
    `margin` neighbours however the timestamps jitter. The witness's stamp is
    recorded, not required: its entry rows are what the stored stream
    says, and a reader asking outside them gets the refusal."""
    if not portrait_rows:
        return None, "no stored killfeed_portrait rows"
    got = portrait_rows[0].get("killfeed_portrait_version")
    t = np.unique(np.asarray([float(r["t_ms"]) for r in portrait_rows
                              if r.get("kind") == "portrait_observation"
                              and r.get("role") in KILLFEED_PANEL_GATE_ROLES], float))
    step = 1000.0 / float(hz)
    pad = (int(margin) + 0.5) * step
    lo, hi = np.maximum(t - pad, 0.0), t + pad
    first = np.flatnonzero(np.r_[True, lo[1:] > hi[:-1]]) if len(t) else np.zeros(0, int)
    last = np.r_[first[1:] - 1, len(t) - 1] if len(t) else first
    spans = np.stack([lo[first], hi[last]], axis=1).tolist() if len(t) else []
    return {"witness": "killfeed_portrait", "witness_version": got,
            "roles": list(KILLFEED_PANEL_GATE_ROLES), "margin_samples": int(margin),
            "hz": float(hz), "witness_open": int(len(t)), "spans": spans}, None


def gate_spans(t_ms, open_, margin: int) -> list[list[float]]:
    """Closed spans `[first, last]` of the sample times within `margin`
    samples of an open one, on the timeline `t_ms` (sorted) gives."""
    t = np.asarray(t_ms, float)
    on = np.asarray(open_, bool)
    keep = on.copy()
    for d in range(1, margin + 1):
        keep[d:] |= on[:-d]
        keep[:-d] |= on[d:]
    spans: list[list[float]] = []
    prev = False
    for x, k in zip(t.tolist(), keep.tolist()):
        if k and prev:
            spans[-1][1] = x
        elif k:
            spans.append([x, x])
        prev = k
    return spans


def in_spans(t: float, spans, starts=None) -> bool:
    """Whether `t` lies in one of the closed `spans` (sorted, disjoint);
    `starts`, the spans' first times, saves rebuilding them per call."""
    import bisect
    if starts is None:
        starts = [a for a, _ in spans]
    i = bisect.bisect_right(starts, float(t)) - 1
    return i >= 0 and float(t) <= spans[i][1]


def gate_rule(margin: int) -> str:
    """The name of the frames a scoreboard gate at `margin` keeps: `on`
    (`SCOREBOARD_GATE_RULE`, every strip on-sample) or `on+N`, N samples
    either side as well. A record written before the field held `on+1`."""
    return SCOREBOARD_GATE_RULE if int(margin) == 0 else f"{SCOREBOARD_GATE_RULE}+{int(margin)}"


def scoreboard_gate(strip_rows: list[dict], margin: int = SCOREBOARD_GATE_MARGIN
                    ) -> tuple[dict | None, str | None]:
    """The scoreboard set's gate from a session's stored `scoreboard_strip`
    rows, or None and why there is none.

    The gate is an opportunity, not an outcome: the strip witness reads the
    board present, or cannot read the band (`SCOREBOARD_GATE_VERDICTS`), at
    a sample or within `margin` samples of it. It reads the strip's own
    verdict rather than `adjudication.scoreboard.board_presence`, which
    joins the slab test's opens, the scoreboard reader's own outcome."""
    from .version import SCOREBOARD_STRIP_VERSION
    if not strip_rows:
        return None, "no stored scoreboard_strip rows"
    got = strip_rows[0].get("scoreboard_strip_version")
    if got != SCOREBOARD_STRIP_VERSION:
        return None, f"stored scoreboard_strip rows are at {got}, current is {SCOREBOARD_STRIP_VERSION}"
    samples = sorted((r for r in strip_rows if r.get("kind") == "sample"),
                     key=lambda r: float(r["t_ms"]))
    if not samples:
        return None, "the stored scoreboard_strip rows hold no samples"
    opens = [r["verdict"] in SCOREBOARD_GATE_VERDICTS for r in samples]
    spans = gate_spans([r["t_ms"] for r in samples], opens, margin)
    starts = [a for a, _ in spans]
    return {"witness": "scoreboard_strip", "witness_version": got, "rule": gate_rule(margin),
            "verdicts": list(SCOREBOARD_GATE_VERDICTS), "margin_samples": int(margin),
            "witness_samples": len(samples), "witness_open": int(sum(opens)),
            "samples": sum(in_spans(r["t_ms"], spans, starts) for r in samples),
            "spans": spans}, None


def combat_report_gate(choice: list[dict], report_rows: list[dict], hz: float
                       ) -> tuple[dict | None, str | None]:
    """The combat report set's gate from the owner's per-round choice
    (`adjudication.combat_report.round_frames`) over the stored
    `combat_report` rows, or None and why there is none.

    Each kept round's frame opens a span a quarter sample either side of its
    time, so the writer, offered every frame at the reader's rate, keeps that
    frame alone. The record carries the choice, every round included: a
    round with no frame keeps its reason. A time outside the spans is
    refused as `thinned_out` (`refuse_as`): the gate saw it and dropped it."""
    from .version import COMBAT_REPORT_FRAMES_VERSION
    if not report_rows:
        return None, "no stored combat_report rows"
    frames = [r for r in report_rows if r.get("kind") == "frame"]
    if not frames:
        return None, "the stored combat_report rows hold no frames"
    pad = 0.25 * 1000.0 / float(hz)
    kept = sorted(float(c["t_ms"]) for c in choice if c.get("t_ms") is not None)
    return {"witness": "combat_report",
            "witness_version": report_rows[0].get("combat_report_version"),
            "rule": "one_per_round", "version": COMBAT_REPORT_FRAMES_VERSION,
            "hz": float(hz), "witness_samples": len(frames), "samples": len(kept),
            "refuse_as": "thinned_out", "rounds": json.loads(json.dumps(choice)),
            "spans": [[t - pad, t + pad] for t in kept]}, None


def declare_set(reader, name: str, profile, wh) -> None:
    """Give `reader` the `cache_set` `name` when its `box` is that set's first
    rectangle: its reads are `frame[box]`, so they stay inside the cached
    set only where the box IS the profile's ROI. Its `cache_rois` name that
    ROI alone, so a pass decodes no crop it never reads, such as a tray
    the cache holds only on its grid (`GRID_ROIS`)."""
    if list(reader.box) == roi_rects(name, profile, wh)[0]:
        reader.cache_set = name
        reader.cache_rois = (CACHE_SETS[name][0],)


def grid_times(t_ms, t0: float, t1: float, step_s: float) -> list[float]:
    """The first cached time at or after each point of a `step_s` grid that
    starts at the first cached time inside [t0, t1], within [t0, t1].

    This is how a reader slower than its cache reads it (`cache_resample`):
    a 4 Hz grid over a 15 Hz cache averages 4 Hz, each time within one cache
    interval after its grid point, where striding from the last sample taken
    would drift below the rate asked."""
    t = np.unique(np.asarray(t_ms, float))
    t = t[(t >= t0) & (t <= t1)]
    if not len(t):
        return []
    want = np.arange(t[0], t[-1] + 1, step_s * 1000.0)
    return [float(x) for x in t[np.unique(np.searchsorted(t, want).clip(0, len(t) - 1))]]


def grid_keep(t_ms, spans, step_s: float) -> np.ndarray:
    """The cached times a grid-thinned ROI keeps (`GRID_ROIS`): the union
    over the cache's round `spans` of `grid_times` at `step_s`, the times
    `cli._tray_samples` and `cli._tray_frames` read, sorted."""
    got = {x for a, b in spans for x in grid_times(t_ms, float(a), float(b), step_s)}
    return np.asarray(sorted(got), float)


class GridPicker:
    """`grid_keep` decided as frames arrive, for a writer that cannot hold a
    round's crops: `offer(t)` returns the times now known to be kept, in
    order, the frame at `t` included where a grid point lies in (previous
    frame, t]. A span's last frame is kept also where the grid's final point
    lies past it (`grid_times` clips that point to it); that is known only
    when a later frame or `close()` ends the span, so the picker holds that
    one frame back (`pending`). Grid points are numpy's `arange` values,
    `t0 + i * ((t0 + step) - t0)`, so the picks equal `grid_times` exactly;
    the writer checks them against `grid_keep` when it finishes."""

    def __init__(self, spans, step_s: float):
        self.spans = [(float(a), float(b)) for a, b in spans]
        self.step = float(step_s) * 1000.0
        # Per span: first time, grid delta, next grid index, last time seen.
        self.state = [None] * len(self.spans)
        self.pending: float | None = None

    def _in(self, t: float) -> list[int]:
        return [i for i, (a, b) in enumerate(self.spans) if a <= t <= b]

    def _edge(self, i: int, t_last: float) -> bool:
        t0, _d, k, _ = self.state[i]
        n = len(np.arange(t0, t_last + 1, self.step))
        return k < n

    def offer(self, t: float) -> list[float]:
        t = float(t)
        out: list[float] = []
        if self.pending is not None:
            p, self.pending = self.pending, None
            # The pending frame was a span's last where `t` left that span.
            if any(self._edge(i, p) for i in self._in(p) if not self.spans[i][0] <= t <= self.spans[i][1]):
                out.append(p)
        picked = False
        last_in = False
        for i in self._in(t):
            st = self.state[i]
            if st is None:
                st = [t, (t + self.step) - t, 0, t]
            t0, d, k, _ = st
            while t0 + k * d <= t:
                k += 1
                picked = True
            self.state[i] = [t0, d, k, t]
            last_in = True
        if picked:
            out.append(t)
        elif last_in:
            self.pending = t
        return out

    def close(self) -> list[float]:
        """The pending frame where it is kept as its span's last."""
        if self.pending is None:
            return []
        p, self.pending = self.pending, None
        return [p] if any(self._edge(i, p) for i in self._in(p)) else []


def nearest_times(t_ms, asked, held, step_s: float) -> list[float]:
    """The cached time nearest each point of a `step_s` grid phased at the
    start of each `asked` span, for the grid points inside `held` spans,
    each pick taken inside the held span that holds its point.

    This is the rule of a reader that declares `cache_resample = "nearest"`:
    a decode's stride restarts at each span the reader asked for, from the
    first frame at or after its start, and steps by `step_s` from there
    (`decode.sample_multi`), so the grid is that stride's phase. `held` is the
    reader's spans after a clip to the cache's rounds (`clip_record`), and a
    grid point outside them is unread, as the clip records. On a 60 fps
    capture a 15 Hz cache holds every 4th or 5th frame, so each pick sits
    within about 42 ms of the frame the decode would take, and on it where
    the cache holds that frame."""
    t = np.unique(np.asarray(t_ms, float))
    step = step_s * 1000.0
    out: set[float] = set()
    for a, b in asked:
        grid = np.arange(float(a), float(b) + 1e-9, step)
        for lo, hi in held:
            g = grid[(grid >= lo) & (grid <= hi)]
            tt = t[(t >= lo) & (t <= hi)]
            if not len(g) or not len(tt):
                continue
            j = np.searchsorted(tt, g).clip(0, len(tt) - 1)
            jm = (j - 1).clip(0, len(tt) - 1)
            pick = np.where(np.abs(tt[jm] - g) <= np.abs(tt[j] - g), jm, j)
            out.update(float(x) for x in tt[pick])
    return sorted(out)


def resamples(reader, cache_hz: float) -> bool:
    """Whether `reader` reads a cache written faster than its own rate on
    its own grid (`grid_times`, or `nearest_times` for `"nearest"`): it
    declares `cache_resample` and its rate is below the cache's."""
    return bool(getattr(reader, "cache_resample", False)) and float(reader.hz) < float(cache_hz)


def covers(held, wanted) -> bool:
    """Whether cached `held` spans contain every `wanted` span; `wanted` None
    is the whole capture, which only an unbounded cache holds."""
    if wanted is None:
        return False
    return all(any(a <= s and e <= b for a, b in held) for s, e in wanted)


def clip_spans(wanted, held) -> list[tuple[float, float]]:
    """`wanted` spans cut to what `held` spans contain; `wanted` None is the
    whole capture, so the result is `held` itself."""
    if wanted is None:
        return [(float(a), float(b)) for a, b in held]
    out = []
    for s, e in wanted:
        for a, b in held:
            lo, hi = max(s, a), min(e, b)
            if lo < hi:
                out.append((float(lo), float(hi)))
    return sorted(out)


#: How `scan --from` picks a pass's frames.
FRAME_SOURCES = ("auto", "cache", "video")


def subtract_spans(wanted, taken) -> list[tuple[float, float]]:
    """The parts of `wanted` spans that no `taken` span holds."""
    out = []
    for s, e in wanted:
        pieces = [(float(s), float(e))]
        for a, b in taken:
            pieces = [p for lo, hi in pieces
                      for p in ((lo, min(hi, a)), (max(lo, b), hi)) if p[0] < p[1]]
        out.extend(pieces)
    return sorted(out)


def clip_record(asked, read, record: dict, reason: str = "outside_cache_rounds") -> dict:
    """What a clip to a round cache did to a reader, for its stream's
    provenance: the cache that fed it, the spans it asked for, read and
    skipped. A skipped span is unread, not unobserved: nothing looked
    there. `asked` None is the whole capture, whose skipped part is
    everything outside `spans_read`. A decode clipped to the live rounds
    (`clip_live_rounds`) passes `{"version": "video", "roi": None}` and
    `reason` `outside_live_rounds`."""
    pairs = lambda spans: [[float(a), float(b)] for a, b in spans]
    return {"frames_from": record["version"], "cache_set": record["roi"],
            "reason": reason,
            "spans_asked": None if asked is None else pairs(asked),
            "spans_read": pairs(read),
            "spans_skipped": None if asked is None else pairs(subtract_spans(asked, read))}


def clip_live_rounds(readers, live_rounds) -> list[str]:
    """Clip each decoded reader that declares `live_rounds_only` to the
    session's live rounds, the spans a minimap round cache is written over
    (`scan --cache-live`: each round from `LIVE_LEAD_MS` before its barrier
    drop); the lines that say what it did.

    A decode reads what `--from cache` reads: the reader's spans cut to the
    rounds, its stride restarted at each cut span as the cache writer's
    is, and `spans_clip` records the time left unread with reason
    `outside_live_rounds`. `live_rounds()` returns the spans, or None and
    why; without them the reader keeps its spans and the line says so. A
    reader the cache path already clipped (`spans_clip`) is left alone."""
    notes: list[str] = []
    todo = [r for r in readers if getattr(r, "live_rounds_only", False)
            and getattr(r, "spans_clip", None) is None]
    if not todo:
        return notes
    rounds, why = live_rounds()
    for r in todo:
        if rounds is None:
            notes.append(f"spans      {r.name} kept: no live rounds to clip it to ({why})")
            continue
        asked = getattr(r, "spans", None)
        r.spans = clip_spans(asked, rounds)
        r.spans_clip = clip_record(asked, r.spans, {"version": "video", "roi": None},
                                   reason="outside_live_rounds")
        skipped = r.spans_clip["spans_skipped"]
        notes.append(f"spans      {r.name} clipped to the {len(rounds)} live rounds"
                     + ("" if skipped is None else
                        f"; {sum(b - a for a, b in skipped) / 1000.0:.0f} s of its spans "
                        f"left unread, recorded as spans_skipped"))
    return notes


def rounds_covered(held, wanted, rounds) -> tuple[bool, str]:
    """Whether a cache written over rounds (`held`) holds a span reader's
    window, and why: the reader's `wanted` spans inside the session's live
    `rounds`, the spans a live-round cache is written over.

    A round cache never holds the buy phase before each round's lead, so the
    window leaves it out: `--from cache` reads the rounds only, and `--from
    auto` reads what `--from cache` would. What the window asks the cache
    must hold whole; a cache missing a round, or written before the rounds
    moved, holds part of it, and the pass decodes."""
    if wanted is None:
        return False, "it reads the whole capture, and the cache holds rounds"
    window = clip_spans(wanted, rounds)
    if not window:
        return False, "its spans meet no live round"
    out = [w for w in window if not covers(held, [w])]
    if out:
        return False, (f"{len(out)} of its {len(window)} in-round spans lie outside "
                       f"the cache's {len(held)} rounds")
    return True, f"the cache holds its spans inside all {len(rounds)} live rounds"


def choose_source(store_root: Path, manifest: dict, profile, readers, mode: str,
                  live_rounds) -> tuple["RoiCache | None", str, list[str]]:
    """The cache that feeds a pass (None to decode), why, and the lines that
    say what the choice did to the readers' spans.

    `mode` is `FRAME_SOURCES`'s. `video` decodes. `cache` clips every reader
    of a cache written over rounds to those rounds, then asks `cache_for`;
    None there means the caller refuses. `auto` clips a span reader the same
    way only where `rounds_covered` says its cache holds its window, asking
    `live_rounds()` -- the session's live-round spans, or None and why --
    once, when a round cache first needs it. If `cache_for` then refuses the
    pass, auto puts every clipped reader's spans back and the pass decodes
    them whole, so a decode never reads clipped spans. A whole-capture reader
    is never clipped under auto: a round cache does not hold it, and
    `cache_for` says so.

    Each clipped reader carries `spans_clip` (`clip_record`), which its
    stream must record, so a skipped span reads as unread rather than as
    a span with nothing in it; a restored reader loses it. Auto clips only
    a reader that declares `records_clip`; under `cache` the caller refuses
    a clipped reader that does not. Under `auto` and
    `cache` a cache-fed pass reads the same frames and records the same
    clip, so the two write the same streams; the source changes no stamp."""
    if mode not in FRAME_SOURCES:
        raise ValueError(f"frame source {mode!r} is not one of {FRAME_SOURCES}")
    if mode == "video":
        return None, "--from video", []
    notes: list[str] = []
    before: list[tuple[object, object]] = []
    rounds: list | None = None
    rounds_why = None
    for r in readers:
        s = getattr(r, "cache_set", None)
        held = RoiCache.load(store_root, manifest, profile, s)[0] if s else None
        if held is None or held.record.get("spans") is None:
            continue
        spans = held.record["spans"]
        if mode == "auto":
            if getattr(r, "spans", None) is None:
                continue
            if not getattr(r, "records_clip", False):
                notes.append(f"spans      {r.name} kept: its stream cannot record the "
                             f"spans a clip to the {s} cache's rounds would skip")
                continue
            if rounds is None and rounds_why is None:
                rounds, rounds_why = live_rounds()
                rounds_why = rounds_why or ""
            if rounds is None:
                notes.append(f"spans      {r.name} kept: no live rounds to check the "
                             f"{s} cache against ({rounds_why})")
                continue
            ok, why = rounds_covered(spans, r.spans, rounds)
            if not ok:
                notes.append(f"spans      {r.name} kept: {why}")
                continue
            notes.append(f"spans      {r.name}: {why}")
        asked = getattr(r, "spans", None)
        before.append((r, asked))
        r.spans = clip_spans(asked, spans)
        r.spans_clip = clip_record(asked, r.spans, held.record)
        skipped = r.spans_clip["spans_skipped"]
        notes.append(f"spans      {r.name} clipped to the {s} cache's {len(spans)} rounds"
                     + ("" if skipped is None else
                        f"; {sum(b - a for a, b in skipped) / 1000.0:.0f} s of its spans "
                        f"left unread, recorded as spans_skipped"))
    cache, why = cache_for(store_root, manifest, profile, readers, gated_ok=mode == "cache")
    if cache is None and mode == "auto" and before:
        for r, spans in before:
            r.spans = spans
            del r.spans_clip
        notes.append(f"spans      {', '.join(r.name for r, _ in before)} restored: "
                     f"the pass decodes")
    return cache, why, notes


def cache_dir(store_root: Path, name: str) -> Path:
    return Path(store_root) / "roi_cache" / name / ROI_CACHE_VERSION


def stored_record(store_root: Path, sid: str, name: str) -> dict | None:
    """The stored cache record of set `name` for `sid`, unchecked; None where
    none is stored."""
    meta = cache_dir(store_root, name) / f"{sid}.json"
    return json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else None


def rewrite_command(sid: str, name: str, record: dict | None = None) -> str:
    """The scan that re-decodes set `name`'s crop cache for `sid` at the rects
    the manifest names now (`roi_rects`), at the stored record's rate and, where
    it held round spans, over the live rounds again."""
    cmd = f"reticle scan {sid} --only roi_cache --cache-roi {name}"
    if record is not None:
        if record.get("hz") is not None:
            cmd += f" --cache-hz {float(record['hz']):g}"
        if record.get("spans"):
            cmd += " --cache-live"
    return cmd


def _raw_rects_ok(rec: dict, want: list[list[int]]) -> bool:
    """Whether a raw read (`RoiCache.load(raw=True)`) may use a cache whose
    rectangles differ from the ones the manifest names now: only its minimap
    rectangle may differ. The raw read takes the minimap crop at the box it
    was cut with (`stored_rect`), and the placement fit compares that box with
    the one it needs, so a stored capture box wider than the cache's crop
    never refuses the fit that would name it."""
    held = CACHE_SETS[rec["roi"]]
    got = [list(r) for r in rec["rects"]]
    return ("minimap" in held and len(got) == len(want)
            and all(g == w for r, g, w in zip(held, got, want) if r != "minimap"))


def _cache_record(manifest: dict, profile, name: str, rects, hz: float, spans=None,
                  gate=None) -> dict:
    rec = {"version": ROI_CACHE_VERSION, "roi": name, "rects": [list(r) for r in rects],
           "hz": hz, "spans": None if spans is None else [[float(a), float(b)] for a, b in spans],
           "codec": CODECS.get(name, "png"), "session_id": manifest["session_id"], "profile": profile.name,
           "content_key": manifest["source"].get("content_key"),
           "wh": [int(manifest["source"]["width"]), int(manifest["source"]["height"])]}
    if gate is not None:
        rec["gate"] = json.loads(json.dumps(gate))
    return rec


def holding_sets(need) -> list[str]:
    """The `CACHE_SETS` names whose ROIs include every ROI in `need`, the
    smallest first: the sets `cache_for` tries for a pass."""
    return sorted((n for n, rs in CACHE_SETS.items() if set(need) <= set(rs)),
                  key=lambda n: len(CACHE_SETS[n]))


#: The crop cache sets each `reticle scan --only <channel>` pass's readers
#: declare (`cache_set`, `declare_set`, set where `scan` builds them): the HUD
#: reader and the killfeed portraits read `hud` and `killfeed`, the roster
#: `hud`, the minimap readers `minimap`. A channel absent here has a reader
#: that declares no set (pings, the scoreboard), so its pass decodes, or one
#: that reads only a gated set: the combat report reader reads its
#: one-frame-per-round set under `--from cache` (`cache_for`'s `gated_ok`).
SCAN_CHANNEL_SETS = {
    "hud": ("hud", "killfeed"),
    "roster": ("hud",),
    "minimap": ("minimap",),
    "ally_icon": ("minimap",),
    "minimap_dark": ("minimap",),
}


def channel_cache(store_root: Path, manifest: dict, profile, channel: str
                  ) -> tuple[str | None, str]:
    """The stored, ungated cache set that holds every ROI a `scan --only
    <channel>` pass reads, or None and why. The store-only half of
    `cache_for`: `plan` asks it before proposing a cache-fed reread of a
    session whose video is retired; `scan` still decides with the readers'
    rates and spans, and refuses `source_retired_no_cache` where they do
    not fit."""
    sets = SCAN_CHANNEL_SETS.get(channel)
    if sets is None:
        return None, f"a {channel} reader reads outside any cached ROI set"
    need = set().union(*(CACHE_SETS[s] for s in sets))
    why = "no_cache"
    for name in holding_sets(need):
        cache, reason = RoiCache.load(store_root, manifest, profile, name)
        if cache is None:
            why = reason or why
        elif cache.record.get("gate") is not None:
            why = f"the {name} cache holds only the samples its gate kept"
        else:
            return name, f"the {name} cache ({cache.record['version']}) holds its ROIs"
    return None, why


def cache_for(store_root: Path, manifest: dict, profile, readers,
              gated_ok: bool = False) -> tuple["RoiCache | None", str]:
    """The cache that can feed this whole pass, or None and why it cannot.

    A pass is fed from the cache only when EVERY reader declares a
    `cache_set` (its reads stay inside those ROIs), wants frames the cache
    holds at the rate it was written, and one stored cache holds the union of
    their ROIs. A cache written over `spans` feeds a reader only inside them:
    one wanting the whole capture, or time outside, needs a decode. One reader
    outside that makes it a decode: a pass is fed from one source.

    A reader that declares `cache_resample` may run slower than the cache: it
    reads the cached times on its own `grid_times`, restarted at each of its spans,
    so neither the rate nor a whole-capture cache's phase refuses it. Those
    times are the cache's frames, not the ones a decode's stride would pick;
    a `"nearest"` reader takes the cached frame nearest each of them
    (`nearest_times`).

    A gated cache holds only the frames its gate kept. It feeds a pass only
    with `gated_ok` (`--from cache`) and only where every reader declares
    `reads_gate`: such a reader stores each frame the gate dropped as a
    refusal (`unheld_frames`), never as a frame with nothing in it.
    """
    need: set[str] = set()
    for r in readers:
        s = getattr(r, "cache_set", None)
        if s is None:
            return None, f"{r.name} reads outside any cached ROI set"
        need |= set(CACHE_SETS[s])
    names = holding_sets(need)
    if not names:
        return None, f"no cached set holds {sorted(need)}"
    why = "no_cache"
    for name in names:
        cache, reason = RoiCache.load(store_root, manifest, profile, name)
        if cache is None:
            why = reason or why
            continue
        if cache.record.get("gate") is not None and not (
                gated_ok and all(getattr(r, "reads_gate", False) for r in readers)):
            # It holds the frames its gate kept, not every frame at its rate.
            return None, (f"the {cache.record['roi']} cache holds only the samples its "
                          f"{cache.record['gate']['witness']} gate kept")
        hz = float(cache.record["hz"])
        bad = [r.name for r in readers if float(r.hz) != hz and not resamples(r, hz)]
        if bad:
            return None, f"{', '.join(bad)} at another rate than the cache's {cache.record['hz']} Hz"
        held = cache.record.get("spans")
        if held is None:
            # A whole-capture cache samples on one stride from the start; a
            # decode over spans restarts it at each span, on other frames.
            out = [r.name for r in readers
                   if getattr(r, "spans", None) is not None and not resamples(r, hz)]
            if out:
                return None, f"{', '.join(out)} reads spans, and the cache holds the whole capture"
        else:
            out = [r.name for r in readers if not covers(held, getattr(r, "spans", None))]
            if out:
                return None, f"{', '.join(out)} reads outside the cache's spans"
        return cache, f"{cache.record['roi']} cache ({cache.record['version']})"
    return None, why


class RoiCacheWriter:
    """A reader that joins a decode pass and stores a set's crops.

    With a `gate` (`scoreboard_gate`), it is offered every frame at its rate
    and stores only those inside the gate's spans, so the frames it holds are
    the ones a whole-capture reader at that rate reads: spans of its own
    would restart the stride at each span, on other frames.

    Over round `spans`, a ROI in `GRID_ROIS` (the tray) is stored only on
    its readers' grid (`GridPicker`, checked against `grid_keep` at
    `finish`); the set's other rectangles keep every frame."""

    def __init__(self, store_root: Path, manifest: dict, profile, name: str = "killfeed",
                 hz: float = 2.0, spans=None, gate: dict | None = None):
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        if gate is not None and spans is not None:
            raise ValueError("a gated cache rides the whole capture; it takes no spans")
        self.rects = roi_rects(name, profile, wh, manifest)
        self.record = _cache_record(manifest, profile, name, self.rects, hz, spans, gate)
        self.name = f"roi_cache:{name}"
        self.hz, self.spans = hz, spans
        self.gate = self.record.get("gate")
        self._starts = None if self.gate is None else [a for a, _ in self.gate["spans"]]
        self.frames_offered = 0
        # `(t_ms, frame_idx)` of every frame offered, for a `TIMELINE_SETS` set.
        self._offered: list[tuple[float, int]] | None = [] if name in TIMELINE_SETS else None
        #: Called at `finish` where set: a dict it returns is recorded as
        #: `gate_recheck` (the scan checks the gate's witness rows against
        #: the same reader's rows in this pass).
        self.recheck = None
        # Grid-thinned rects: rect index -> (ROI, step, picker); a held-back
        # crop (`GridPicker.pending`) waits in `_held` until its span ends.
        grid = GRID_ROIS.get(name, {}) if spans is not None and self.record["codec"] == "ffv1" else {}
        self._grid = {CACHE_SETS[name].index(roi): (roi, step, GridPicker(spans, step))
                      for roi, step in grid.items()}
        self._held: dict[int, tuple[float, int, np.ndarray]] = {}
        self._counts = [0] * len(self.rects)
        d = cache_dir(store_root, name)
        d.mkdir(parents=True, exist_ok=True)
        sid = manifest["session_id"]
        self.codec = self.record["codec"]
        self.paths = (d / f"{sid}.bin", d / f"{sid}.idx.npy", d / f"{sid}.json")
        self.offered_path = d / f"{sid}.offered.npy"
        # One row per frame per rectangle: t_ms, frame_idx, rect, offset, length;
        # for video, offset is the frame's number in its rect's file.
        self._index: list[tuple[float, int, int, int, int]] = []
        self._offset = 0
        if self.codec == "ffv1":
            ff = ffmpeg_path()
            self.videos = [d / f"{sid}.r{k}.mkv" for k in range(len(self.rects))]
            self._procs = []
            for (x0, y0, x1, y1), path in zip(self.rects, self.videos):
                part = path.with_suffix(".part.mkv")
                self._procs.append(subprocess.Popen(
                    ffv1_command(ff, x1 - x0, y1 - y0, hz, part), stdin=subprocess.PIPE))
            self._count = 0
        else:
            self._part = self.paths[0].with_suffix(".bin.part")
            self._fh = open(self._part, "wb")

    def feed(self, smp) -> None:
        self.frames_offered += 1
        if self._offered is not None:
            self._offered.append((float(smp.t_ms), int(smp.frame_idx)))
        if self.gate is not None and not in_spans(smp.t_ms, self.gate["spans"], self._starts):
            return
        if self.codec == "ffv1":
            t = float(smp.t_ms)
            for k, ((x0, y0, x1, y1), proc) in enumerate(zip(self.rects, self._procs)):
                crop = np.ascontiguousarray(smp.frame[y0:y1, x0:x1])
                if k in self._grid:
                    held = self._held.pop(k, None)
                    for kept in self._grid[k][2].offer(t):
                        if kept == t:
                            self._write(k, t, int(smp.frame_idx), crop)
                        elif held is not None and kept == held[0]:
                            self._write(k, *held)
                    if self._grid[k][2].pending == t:
                        self._held[k] = (t, int(smp.frame_idx), crop.copy())
                    continue
                self._write(k, t, int(smp.frame_idx), crop)
            self._count += 1
            return
        for k, (x0, y0, x1, y1) in enumerate(self.rects):
            ok, png = cv2.imencode(".png", smp.frame[y0:y1, x0:x1])
            if not ok:
                raise ValueError(f"could not encode the crop at {smp.t_ms} ms")
            b = png.tobytes()
            self._fh.write(b)
            self._index.append((float(smp.t_ms), int(smp.frame_idx), k, self._offset, len(b)))
            self._offset += len(b)

    def _write(self, k: int, t: float, frame_idx: int, crop: np.ndarray) -> None:
        """One crop to rect `k`'s encoder, indexed at its frame number there."""
        self._procs[k].stdin.write(crop.tobytes())
        self._index.append((t, frame_idx, k, self._counts[k], 0))
        self._counts[k] += 1

    def _finish_grid(self) -> None:
        """Write each grid rect's held-back crop where its span's end keeps
        it, then check the kept times against `grid_keep` over every stored
        time: a writer that kept other frames than the readers read fails
        here, never silently. Records the thinning under `thinned_rois`."""
        for k, (roi, step, picker) in self._grid.items():
            held = self._held.pop(k, None)
            for kept in picker.close():
                if held is not None and kept == held[0]:
                    self._write(k, *held)
        if not self._grid:
            return
        rows = np.array(self._index, dtype=np.float64).reshape(-1, 5)
        every = rows[:, 0][rows[:, 2] == 0]
        thinned = {}
        for k, (roi, step, _picker) in self._grid.items():
            got = np.sort(rows[:, 0][rows[:, 2] == k])
            want = grid_keep(every, self.spans, step)
            if not np.array_equal(got, want):
                raise RuntimeError(f"the {roi} grid kept {len(got)} frames where grid_keep keeps "
                                   f"{len(want)}; the writer's picks are not the readers' grid")
            thinned[roi] = {"version": GRID_THIN_VERSION, "rule": "grid_keep", "step_s": step,
                            "spans": "record", "frames_kept": int(len(got)),
                            "frames_set": int(len(np.unique(every))),
                            "by": "RoiCacheWriter"}
        self.record["thinned_rois"] = thinned

    def _finish_rounds(self) -> None:
        """For a gate that names its frames per round (`combat_report_gate`),
        check the writer kept exactly those frames: a chosen frame this pass
        never offered (another timeline than the stored rows') fails here,
        never silently. Records `recheck`'s answer as `gate_recheck`."""
        if self.gate is None or self.gate.get("rule") != "one_per_round":
            return
        want = np.sort([float(c["t_ms"]) for c in self.gate["rounds"] if c.get("t_ms") is not None])
        got = np.unique(np.asarray([r[0] for r in self._index], float))
        if not np.array_equal(want, got):
            missing = sorted(set(want.tolist()) - set(got.tolist()))
            raise RuntimeError(f"the {self.record['roi']} gate names {len(want)} frames and the "
                               f"writer kept {len(got)}; not offered: {missing[:5]}")
        if self.recheck is not None:
            self.record["gate_recheck"] = json.loads(json.dumps(self.recheck()))

    def finish(self) -> None:
        if self.codec == "ffv1":
            try:
                self._finish_rounds()
                self._finish_grid()
            except Exception:
                for proc, path in zip(self._procs, self.videos):
                    proc.stdin.close()
                    proc.wait()
                    path.with_suffix(".part.mkv").unlink(missing_ok=True)
                raise
            for k, (proc, path) in enumerate(zip(self._procs, self.videos)):
                proc.stdin.close()
                code = proc.wait()
                part = path.with_suffix(".part.mkv")
                if self._counts[k] == 0:
                    # A gate that kept nothing: no video, and an empty index.
                    part.unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
                    continue
                if code != 0:
                    raise RuntimeError(f"ffmpeg failed writing {path}")
                part.replace(path)
            self._offset = sum(p.stat().st_size for p in self.videos if p.is_file())
        else:
            self._fh.close()
            self._part.replace(self.paths[0])
        idx = np.array(self._index, dtype=np.float64).reshape(-1, 5)
        # A held-back grid crop is indexed after the frame that ended its span.
        np.save(self.paths[1], idx[np.lexsort((idx[:, 2], idx[:, 0]))] if self._grid else idx)
        frames = len({t for t, *_ in self._index})
        if self._offered is not None:
            np.save(self.offered_path, np.asarray(self._offered, np.float64).reshape(-1, 2))
        self.paths[2].write_text(json.dumps({**self.record, "frames": frames,
                                             "frames_offered": self.frames_offered,
                                             "bytes": self._offset}, indent=1),
                                 encoding="utf-8")


@dataclass
class RoiCache:
    """A stored cache, checked against the session it claims to hold."""

    record: dict
    t_ms: np.ndarray
    frame_idx: np.ndarray
    rect: np.ndarray
    offset: np.ndarray
    length: np.ndarray
    blob: Path
    #: The session's widget placement (`widget_frame.for_session`), or None
    #: where it reads the baked one; `samples` normalises minimap pixels by it.
    widget: object = None
    #: Rect index -> video file, where a rect is read from beside the store
    #: (`with_index`, a thinned copy checked before it replaces the stored one).
    video_paths: dict | None = None

    def thinned(self, roi: str) -> dict | None:
        """The record of `roi`'s grid thinning (`GRID_ROIS`), or None where
        the cache holds it at every frame."""
        return (self.record.get("thinned_rois") or {}).get(roi)

    def with_index(self, idx: np.ndarray, record: dict, video_paths: dict) -> "RoiCache":
        """This cache read through another index and record, with the rects
        in `video_paths` read from those files: a thinned copy checked
        beside the stored cache, whose placement it shares."""
        return RoiCache(record, idx[:, 0], idx[:, 1].astype(int), idx[:, 2].astype(int),
                        idx[:, 3].astype(np.int64), idx[:, 4].astype(np.int64), self.blob,
                        widget=self.widget, video_paths={**(self.video_paths or {}),
                                                         **video_paths})

    @classmethod
    def _open(cls, d: Path, manifest: dict, profile, raw: bool = False):
        sid = manifest["session_id"]
        meta = d / f"{sid}.json"
        if not meta.is_file():
            return None, "no_cache"
        rec = json.loads(meta.read_text(encoding="utf-8"))
        if "rects" not in rec:                             # the one-rectangle layout
            rec["rects"] = [rec["rect"]]
        wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
        want = {"version": ROI_CACHE_VERSION, "profile": profile.name,
                "content_key": manifest["source"].get("content_key"), "wh": list(wh)}
        for key, v in want.items():
            if rec.get(key) != v:
                return None, f"stale_{key}"
        want_rects = roi_rects(rec["roi"], profile, wh, manifest)
        if want_rects != rec["rects"] and not (raw and _raw_rects_ok(rec, want_rects)):
            return None, "stale_rects"
        idx = np.load(d / f"{sid}.idx.npy")
        if idx.shape[1] == 4:                              # t, frame, offset, length
            idx = np.insert(idx, 2, 0, axis=1)
        got = cls(rec, idx[:, 0], idx[:, 1].astype(int), idx[:, 2].astype(int),
                  idx[:, 3].astype(np.int64), idx[:, 4].astype(np.int64),
                  d / f"{sid}.bin")
        if "minimap" in CACHE_SETS[rec["roi"]] and not raw:
            # A widget drawn elsewhere is read through its placement; one the
            # stored crop cannot hold is refused by name, never read as absent.
            # A side-based session with no placement is refused by name too:
            # its turned half would read as an absent widget.
            from .widget_frame import for_session, refusal_text, unplaced_refusal
            unplaced = unplaced_refusal(manifest)
            if unplaced is not None:
                return None, unplaced
            got.widget = for_session(manifest, got.stored_rect("minimap"), d.parents[2])
            if got.widget is not None and got.widget.refusal is not None:
                return None, refusal_text(got.widget.refusal)
        return got, None

    @classmethod
    def load(cls, store_root: Path, manifest: dict, profile,
             name: str = "killfeed", raw: bool = False) -> tuple["RoiCache | None", str | None]:
        """The cache for set `name`, or one whose rectangles include it; or
        None with the reason no cache can be used. `raw` reads the minimap
        crops as stored, at the box they were cut with, with no placement and
        no placement refusal (`_raw_rects_ok`): the placement fit
        (`widget_frame.fit_placement`) reads them so."""
        need = set(CACHE_SETS[name])
        why = "no_cache"
        for other in [name] + [n for n, rs in CACHE_SETS.items()
                               if n != name and need <= set(rs)]:
            got, reason = cls._open(cache_dir(store_root, other), manifest, profile, raw)
            if got is not None:
                return got, None
            if reason != "no_cache":
                why = reason
        return None, why

    def rect_of(self, roi: str) -> list[int]:
        """Where a reader finds one profile ROI in the frames `samples` yields.

        That is the stored rectangle, except for the minimap of a session whose
        widget is read through a placement: `samples` writes it, resampled,
        at the baked ROI, which a crop of the stored (wider) rectangle would
        miss by its shape."""
        if roi == "minimap" and self.widget is not None:
            return list(self.widget.baked_roi)
        return self.stored_rect(roi)

    def _index_by_t(self) -> dict[float, list[int]]:
        if not hasattr(self, "_by_t"):
            self._by_t: dict[float, list[int]] = {}
            for i, t in enumerate(self.t_ms):
                self._by_t.setdefault(float(t), []).append(i)
        return self._by_t

    def holds(self) -> list[float]:
        """The times the cache holds a frame at, in order."""
        return sorted(self._index_by_t())

    def _missing_grid(self, t_ms: float, rois) -> str | None:
        """The first grid-thinned ROI of `rois` the cache holds no crop of
        at `t_ms`, a time it holds other crops at; None where there is none."""
        rows = self._index_by_t().get(float(t_ms))
        if not rows or not self.record.get("thinned_rois"):
            return None
        held = CACHE_SETS[self.record["roi"]]
        have = {int(self.rect[i]) for i in rows}
        for roi in rois:
            if self.thinned(roi) is not None and roi in held and held.index(roi) not in have:
                return roi
        return None

    def refusal(self, t_ms: float, rois=None) -> str | None:
        """None where the cache holds a frame at `t_ms`; else why it holds
        none: `thinned_out` (the gate it was written under kept a frame there
        and `thin_cache` dropped it, or `rois` names a grid-thinned ROI,
        `GRID_ROIS`, off its grid), `outside_gate` (its gate kept no sample
        there),
        `outside_cache_spans` (it was written over spans that miss it), or
        `not_cached` (no frame was stored at that time)."""
        if float(t_ms) in self._index_by_t():
            if rois is not None and self._missing_grid(
                    t_ms, CACHE_SETS[rois] if isinstance(rois, str) else rois) is not None:
                return "thinned_out"
            return None
        gate = self.record.get("gate")
        if gate is not None and not in_spans(t_ms, gate["spans"]):
            if gate.get("refuse_as"):
                # A gate that saw every frame and dropped this one
                # (`combat_report_gate`).
                return gate["refuse_as"]
            before = (self.record.get("thinned") or {}).get("gate_before")
            if before is not None and in_spans(t_ms, before["spans"]):
                return "thinned_out"
            return "outside_gate"
        spans = self.record.get("spans")
        if spans is not None and not any(a <= float(t_ms) <= b for a, b in spans):
            return "outside_cache_spans"
        return "not_cached"

    def offered(self) -> np.ndarray | None:
        """`(t_ms, frame_idx)` of every frame the writer was offered, in
        order, for a set in `TIMELINE_SETS`; None where none was stored."""
        path = self.blob.with_name(self.blob.name.replace(".bin", ".offered.npy"))
        return np.load(path) if path.is_file() else None

    def stored_rect(self, roi: str) -> list[int]:
        """The pixel rectangle one profile ROI's crops were stored from."""
        return self.record["rects"][CACHE_SETS[self.record["roi"]].index(roi)]

    def crops(self, roi: str):
        """`(frame_idx, t_ms, crop)` of one profile ROI at every cached frame,
        in frame order, the crop alone rather than pasted into a frame; None
        where a stored crop does not decode. PNG caches only."""
        if self.record.get("codec") == "ffv1":
            raise ValueError("crops() reads PNG caches; an FFV1 cache is read through samples()")
        k = CACHE_SETS[self.record["roi"]].index(roi)
        rows = np.where(self.rect == k)[0]
        rows = rows[np.argsort(self.frame_idx[rows], kind="stable")]
        with open(self.blob, "rb") as fh:
            for j in rows:
                fh.seek(int(self.offset[j]))
                buf = fh.read(int(self.length[j]))
                yield (int(self.frame_idx[j]), float(self.t_ms[j]),
                       cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR))

    def samples(self, targets_ms: list[float], rois=None, normalise: bool = True):
        """A Sample per target the cache holds, in target order: the stored
        crops pasted into a black frame of the capture's size. `rois` names
        the profile ROIs to decode (a cache set's, or a list); the rest stay
        black, so a killfeed reader on a `hud` cache decodes one crop, not all.

        A session whose widget sits elsewhere (`widget`) has its minimap
        resampled into the baked frame at the profile's ROI, unless
        `normalise` is False (the placement fit reads the raw crop)."""
        if normalise and self.widget is not None:
            for smp in self.samples(targets_ms, rois, normalise=False):
                yield Sample(frame_idx=smp.frame_idx, t_ms=smp.t_ms,
                             frame=self.widget.normalise(smp.frame, smp.t_ms))
            return
        if isinstance(rois, str):
            rois = CACHE_SETS[rois]
        held = CACHE_SETS[self.record["roi"]]
        keep = (set(range(len(held))) if rois is None
                else {held.index(r) for r in rois if r in held})
        self._index_by_t()
        if self.record.get("thinned_rois") and not isinstance(targets_ms, (list, tuple,
                                                                             np.ndarray)):
            # Targets that arrive one by one (`passes.gated_times`: a gate
            # asked only after the earlier samples were fed) are checked one
            # by one, so the check does not drain the gate ahead of the reads.
            targets_ms = self._thinned_checked(targets_ms, keep, held)
        elif self.record.get("thinned_rois"):
            # A grid-thinned ROI asked off its grid refuses the read: its
            # crop was dropped, and no neighbour or black stands in for it.
            targets_ms = list(targets_ms)
            tg = np.asarray(targets_ms, float)
            some = np.isin(tg, self.t_ms)
            for k in sorted(keep):
                if self.thinned(held[k]) is None:
                    continue
                bad = some & ~np.isin(tg, self.t_ms[self.rect == k])
                if bad.any():
                    raise ThinnedOut(held[k], float(tg[np.argmax(bad)]),
                                     self.thinned(held[k]).get("step_s"))
        w, h = self.record["wh"]
        if self.record.get("codec") == "ffv1":
            yield from self._video_samples(targets_ms, keep, w, h)
            return
        with open(self.blob, "rb") as fh:
            for t in targets_ms:
                got = [i for i in self._by_t.get(float(t), ()) if int(self.rect[i]) in keep]
                if not got:
                    continue
                frame = np.zeros((h, w, 3), np.uint8)
                for i in got:
                    fh.seek(int(self.offset[i]))
                    crop = cv2.imdecode(np.frombuffer(fh.read(int(self.length[i])), np.uint8),
                                        cv2.IMREAD_COLOR)
                    x0, y0, x1, y1 = self.record["rects"][int(self.rect[i])]
                    frame[y0:y1, x0:x1] = crop
                yield Sample(frame_idx=int(self.frame_idx[got[0]]), t_ms=float(t), frame=frame)

    def _thinned_checked(self, targets_ms, keep, held):
        """`samples`' thinned-ROI check, one target at a time: a held target
        that a thinned ROI asked does not hold raises `ThinnedOut`."""
        times = {k: set(self.t_ms[self.rect == k].tolist()) for k in sorted(keep)
                 if self.thinned(held[k]) is not None}
        every = set(self.t_ms.tolist())
        for t in targets_ms:
            t = float(t)
            if t in every:
                for k, held_t in times.items():
                    if t not in held_t:
                        raise ThinnedOut(held[k], t, self.thinned(held[k]).get("step_s"))
            yield t

    def _video_samples(self, targets_ms, keep, w, h):
        """`samples` for an FFV1 cache: one capture per rect, read in order,
        seeking only when a target skips frames."""
        caps, pos = {}, {}
        try:
            for t in targets_ms:
                got = [i for i in self._by_t.get(float(t), ()) if int(self.rect[i]) in keep]
                if not got:
                    continue
                frame = np.zeros((h, w, 3), np.uint8)
                for i in got:
                    k, n = int(self.rect[i]), int(self.offset[i])
                    if k not in caps:
                        caps[k] = cv2.VideoCapture(str((self.video_paths or {}).get(k) or
                                                       self.blob.with_name(self.blob.name.replace(
                                                           ".bin", f".r{k}.mkv"))))
                        pos[k] = 0
                    if pos[k] < n <= pos[k] + GRAB_MAX:
                        # A seek costs about 38 ms (`GRAB_MAX`); a short skip is cheaper grabbed.
                        for _ in range(n - pos[k]):
                            caps[k].grab()
                    elif pos[k] != n:
                        caps[k].set(cv2.CAP_PROP_POS_FRAMES, n)
                    ok, crop = caps[k].read()
                    if not ok:
                        raise ValueError(f"cache video ended before frame {n} (rect {k})")
                    pos[k] = n + 1
                    x0, y0, x1, y1 = self.record["rects"][k]
                    frame[y0:y1, x0:x1] = crop
                yield Sample(frame_idx=int(self.frame_idx[got[0]]), t_ms=float(t), frame=frame)
        finally:
            for c in caps.values():
                c.release()

    @classmethod
    def load_union(cls, store_root: Path, manifest: dict, profile, names
                   ) -> tuple["RoiCacheUnion | None", str | None]:
        """The sets `names` (or a `WIDE_ROIS` name) read as one cache, or
        None and why: a part that will not load, or parts written at
        different rates, whose timelines differ."""
        if isinstance(names, str):
            names = WIDE_ROIS[names][0]
        parts = []
        for name in names:
            got, why = cls.load(store_root, manifest, profile, name)
            if got is None:
                return None, f"{name}: {why}"
            parts.append(got)
        if len({float(p.record["hz"]) for p in parts}) > 1:
            return None, "the sets were written at different rates: " + ", ".join(
                f"{n} {p.record['hz']} Hz" for n, p in zip(names, parts))
        return RoiCacheUnion(parts), None


@dataclass
class RoiCacheUnion:
    """Stored sets read as one cache (`RoiCache.load_union`): a time is held
    only where every part asked holds a frame, the same decoded frame, and
    `samples` pastes each part's crops into one black frame. A reader of a
    region wider than one set (`WIDE_ROIS`) runs on it unchanged."""

    parts: list[RoiCache]

    @property
    def record(self) -> dict:
        """The first part's record, with every part's under `parts`."""
        return {**self.parts[0].record, "parts": [p.record for p in self.parts]}

    def _part_rois(self, rois) -> list[tuple[RoiCache, list[str]]]:
        """Each part with the profile ROIs of `rois` it holds; `rois` is a
        `WIDE_ROIS` name, a set name, a list of ROIs, or None for all."""
        if isinstance(rois, str):
            rois = WIDE_ROIS[rois][1] if rois in WIDE_ROIS else CACHE_SETS[rois]
        out = []
        for p in self.parts:
            held = CACHE_SETS[p.record["roi"]]
            want = list(held) if rois is None else [r for r in rois if r in held]
            if want:
                out.append((p, want))
        return out

    def rect_of(self, roi: str) -> list[int]:
        """Where a reader finds `roi` in the frames `samples` yields; a
        `WIDE_ROIS` name is the bounding box of its ROIs."""
        if roi in WIDE_ROIS:
            rs = np.array([self.rect_of(r) for r in WIDE_ROIS[roi][1]])
            return [int(rs[:, 0].min()), int(rs[:, 1].min()),
                    int(rs[:, 2].max()), int(rs[:, 3].max())]
        for p in self.parts:
            if roi in CACHE_SETS[p.record["roi"]]:
                return p.rect_of(roi)
        raise KeyError(f"no part of this cache holds {roi!r}")

    @staticmethod
    def _frame_at(p: RoiCache, t: float) -> int | None:
        i = p._index_by_t().get(float(t))
        return None if not i else int(p.frame_idx[i[0]])

    def refusal(self, t_ms: float, rois=None) -> str | None:
        """None where every part asked holds the same frame at `t_ms`; else
        the first refusing part's `RoiCache.refusal` (`outside_gate` where
        the killfeed panel gate kept no sample), or `frame_mismatch` where
        the parts hold different frames at that time."""
        parts = self._part_rois(rois)
        for p, _ in parts:
            why = p.refusal(t_ms)
            if why is not None:
                return why
        if len({self._frame_at(p, t_ms) for p, _ in parts}) > 1:
            return "frame_mismatch"
        return None

    def holds(self, rois=None) -> list[float]:
        """The times every part asked holds one frame at, in order."""
        parts = self._part_rois(rois)
        common = set(parts[0][0].holds())
        for p, _ in parts[1:]:
            common &= set(p.holds())
        return sorted(t for t in common if self.refusal(t, rois) is None)

    def samples(self, targets_ms: list[float], rois=None):
        """A Sample per target every part asked holds (`refusal` None), in
        target order: each part's crops pasted into one black frame. A
        target outside is skipped, never yielded black; ask `refusal`."""
        parts = self._part_rois(rois)
        if isinstance(targets_ms, (list, tuple, np.ndarray)):
            held = [float(t) for t in targets_ms if self.refusal(t, rois) is None]
            streams = [p.samples(held, want) for p, want in parts]
        else:
            # Targets that arrive one by one (`passes.gated_times`) stay
            # lazy: each part reads its own copy of the one stream.
            from itertools import tee
            lazy = (float(t) for t in targets_ms if self.refusal(t, rois) is None)
            streams = [p.samples(copy, want)
                       for (p, want), copy in zip(parts, tee(lazy, len(parts)))]
        for got in zip(*streams):
            frame = got[0].frame
            for (p, want), smp in zip(parts[1:], got[1:]):
                for roi in want:
                    x0, y0, x1, y1 = p.rect_of(roi)
                    frame[y0:y1, x0:x1] = smp.frame[y0:y1, x0:x1]
            yield Sample(frame_idx=got[0].frame_idx, t_ms=got[0].t_ms, frame=frame)


def unheld_frames(cache) -> list[tuple[float, int, str]]:
    """`(t_ms, frame_idx, reason)` of each frame on a gated cache's offered
    timeline (`RoiCache.offered`) that it holds no crop for, in order, with
    `RoiCache.refusal`'s reason. A prefix of a cache (`pipeline.PrefixCache`)
    answers for its frames before its limit only. ValueError where the
    cache stored no timeline."""
    base = getattr(cache, "cache", cache)
    off = base.offered()
    if off is None:
        raise ValueError(f"the {base.record['roi']} cache stored no offered timeline; a reader "
                         f"fed from it cannot refuse the frames its gate dropped")
    until = getattr(cache, "until_ms", None)
    keep = ~np.isin(off[:, 0], base.t_ms)
    if until is not None:
        keep &= off[:, 0] < until
    t, fi = off[keep, 0], off[keep, 1].astype(int)
    # `RoiCache.refusal` over the array.
    gate = base.record.get("gate") or {}
    before = (base.record.get("thinned") or {}).get("gate_before")
    in_gate = spans_mask(t, gate["spans"]) if gate else np.ones(len(t), bool)
    was = spans_mask(t, before["spans"]) if before else np.zeros(len(t), bool)
    out = gate.get("refuse_as") or np.where(was, "thinned_out", "outside_gate")
    why = np.where(in_gate, "not_cached", out)
    return list(zip(t.tolist(), fi.tolist(), why.tolist()))


def spans_mask(t_ms, spans) -> np.ndarray:
    """Per time in `t_ms`, whether it lies in one of the closed `spans`
    (sorted, disjoint): `in_spans` over an array."""
    t = np.asarray(t_ms, float)
    if not len(spans):
        return np.zeros(t.shape, bool)
    s = np.asarray(spans, float)
    i = np.searchsorted(s[:, 0], t, side="right") - 1
    ok = i >= 0
    out = np.zeros(t.shape, bool)
    out[ok] = t[ok] <= s[i[ok], 1]
    return out


def spans_within(inner, outer) -> bool:
    """Whether every closed span of `inner` lies inside one span of `outer`
    (both sorted, disjoint)."""
    if not len(inner):
        return True
    if not len(outer):
        return False
    a, o = np.asarray(inner, float), np.asarray(outer, float)
    i = np.searchsorted(o[:, 0], a[:, 0], side="right") - 1
    ok = i >= 0
    return bool(ok.all() and np.all(a[:, 1] <= o[i, 1]))


def thin_cache(src: Path, sid: str, gate: dict, dst: Path, tool: str) -> dict:
    """Re-encode the gated FFV1 cache of `sid` in directory `src` under a
    narrower `gate` (a `scoreboard_gate` record) into directory `dst`, never
    over `src`. No capture is decoded: the cached frames are decoded in
    order, one thread, and those inside `gate` piped to the writer's own
    encoder (`ffv1_command`). FFV1 is lossless, so a kept frame keeps its
    pixels; packets are not remuxed, since a cached frame depends on the
    coder state of the frames before it.

    The new index keeps each kept row's time and frame, renumbered; the new
    record carries `gate` and `thinned`: the rule, the tool, the gate it was
    written under (`gate_before`, which `RoiCache.refusal` reads to say
    `thinned_out`), and the frames and bytes before and kept."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("thin_cache writes beside the cache, never over it")
    rec = json.loads((src / f"{sid}.json").read_text(encoding="utf-8"))
    if rec.get("codec") != "ffv1" or len(rec["rects"]) != 1:
        raise ValueError(f"{sid}: thin_cache re-encodes one-rect FFV1 caches")
    before = rec.get("gate")
    if before is None:
        raise ValueError(f"{sid}: the cache has no gate to thin under")
    if rec.get("thinned") is not None:
        raise ValueError(f"{sid}: the cache is already thinned; thin the original")
    if not spans_within(gate["spans"], before["spans"]):
        raise ValueError(f"{sid}: the new gate reaches outside the gate the cache was written under")
    idx = np.load(src / f"{sid}.idx.npy")
    keep = spans_mask(idx[:, 0], gate["spans"])
    dst.mkdir(parents=True, exist_ok=True)
    video, out = src / f"{sid}.r0.mkv", dst / f"{sid}.r0.mkv"
    x0, y0, x1, y1 = rec["rects"][0]
    n_in = 0
    if keep.any():
        part = out.with_suffix(".part.mkv")
        proc = subprocess.Popen(ffv1_command(ffmpeg_path(), x1 - x0, y1 - y0, rec["hz"], part,
                                             threads=1), stdin=subprocess.PIPE)
        cap = cv2.VideoCapture(str(video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
        try:
            while True:
                ok, crop = cap.read()
                if not ok:
                    break
                if n_in < len(keep) and keep[n_in]:
                    proc.stdin.write(np.ascontiguousarray(crop).tobytes())
                n_in += 1
        finally:
            cap.release()
            proc.stdin.close()
            code = proc.wait()
        if code != 0 or n_in != len(idx):
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{sid}: decoded {n_in} of {len(idx)} cached frames, "
                               f"ffmpeg exit {code}")
        part.replace(out)
    new_idx = idx[keep].copy()
    new_idx[:, 3] = np.arange(len(new_idx))
    np.save(dst / f"{sid}.idx.npy", new_idx)
    size = out.stat().st_size if out.is_file() else 0
    record = {**rec, "gate": json.loads(json.dumps(gate)), "frames": int(keep.sum()),
              "bytes": int(size),
              "thinned": {"rule": gate.get("rule"), "tool": tool,
                          "gate_before": before, "frames_before": int(len(idx)),
                          "bytes_before": int(video.stat().st_size) if video.is_file() else 0,
                          "frames_kept": int(keep.sum())}}
    (dst / f"{sid}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"frames_before": int(len(idx)), "frames_kept": int(keep.sum()),
            "frames_decoded": n_in, "bytes_before": record["thinned"]["bytes_before"],
            "bytes_after": int(size)}


def _rect_rows(idx: np.ndarray, rect: int) -> np.ndarray:
    """The index rows of one rect in its video's frame order; a four-column
    index (one rect, no rect column) is rect 0's."""
    if idx.shape[1] == 4:
        idx = np.insert(idx, 2, 0, axis=1)
    rows = idx[idx[:, 2] == rect]
    return rows[np.argsort(rows[:, 3], kind="stable")]


def compare_thinned(src: Path, dst: Path, sid: str, rect: int = 0) -> dict:
    """Every frame of rect `rect` of the thinned cache in `dst` against the
    stored one in `src`, read in order and compared bit for bit:
    `identical`, `different`, `extra_frames` (the thinned video runs past
    its index) and `index_ok` (each kept row's time and frame are a stored
    row's, and each video's frames are its rows, in time order)."""
    old = _rect_rows(np.load(Path(src) / f"{sid}.idx.npy"), rect)
    new = _rect_rows(np.load(Path(dst) / f"{sid}.idx.npy"), rect)
    j = np.searchsorted(old[:, 0], new[:, 0]).clip(0, max(len(old) - 1, 0))
    index_ok = bool(len(old) or not len(new)) and bool(
        np.all(old[j, 0] == new[:, 0]) and np.all(old[j, 1] == new[:, 1])
        and np.all(np.diff(old[:, 0]) > 0)
        and np.array_equal(old[:, 3], np.arange(len(old)))
        and np.array_equal(new[:, 3], np.arange(len(new))))
    keep = set(j.tolist()) if index_ok else set()
    same = differ = 0
    extra = False
    if len(new):
        a = cv2.VideoCapture(str(Path(src) / f"{sid}.r{rect}.mkv"), cv2.CAP_FFMPEG,
                             [cv2.CAP_PROP_N_THREADS, 1])
        b = cv2.VideoCapture(str(Path(dst) / f"{sid}.r{rect}.mkv"), cv2.CAP_FFMPEG,
                             [cv2.CAP_PROP_N_THREADS, 1])
        try:
            for i in range(len(old)):
                ok1, x = a.read()
                if i in keep:
                    ok2, y = b.read()
                    if ok1 and ok2 and np.array_equal(x, y):
                        same += 1
                    else:
                        differ += 1
            extra = bool(b.read()[0])
        finally:
            a.release()
            b.release()
    return {"checked": int(len(new)), "identical": same, "different": differ,
            "extra_frames": extra, "index_ok": bool(index_ok)}


def grid_thin_rect(src: Path, sid: str, roi: str, dst: Path, tool: str) -> dict:
    """Re-encode one grid-thinned ROI's video (`GRID_ROIS`) of the stored
    cache of `sid` in directory `src` to the frames its readers' grid reads
    (`grid_keep` over the record's round spans), into directory `dst`, never
    over `src`. No capture is decoded: the rect's cached frames are decoded
    in order, one thread, and the kept ones piped to the writer's encoder
    (`ffv1_command`); FFV1 is lossless, so a kept frame keeps its pixels.
    The other rects' videos are not copied: the new index keeps their rows
    unchanged, so the copy is read beside the stored files
    (`RoiCache.with_index`) until it replaces them.

    Writes `{sid}.r{k}.mkv`, `{sid}.idx.npy` and `{sid}.json` into `dst`; the
    record carries `thinned_rois[roi]`: the stamp, the rule, the step, the
    tool, and the frames and bytes before and kept."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("grid_thin_rect writes beside the cache, never over it")
    rec = json.loads((src / f"{sid}.json").read_text(encoding="utf-8"))
    step = GRID_ROIS.get(rec["roi"], {}).get(roi)
    if step is None:
        raise ValueError(f"{sid}: {roi} is not a grid-thinned ROI of the {rec['roi']} set")
    if rec.get("codec") != "ffv1":
        raise ValueError(f"{sid}: grid_thin_rect re-encodes FFV1 caches")
    if not rec.get("spans"):
        raise ValueError(f"{sid}: a whole-capture cache keeps every {roi} frame")
    if (rec.get("thinned_rois") or {}).get(roi) is not None:
        raise ValueError(f"{sid}: {roi} is already thinned")
    k = CACHE_SETS[rec["roi"]].index(roi)
    idx = np.load(src / f"{sid}.idx.npy")
    if idx.shape[1] == 4:
        idx = np.insert(idx, 2, 0, axis=1)
    rows = _rect_rows(idx, k)
    if not np.array_equal(rows[:, 3], np.arange(len(rows))):
        raise ValueError(f"{sid}: rect {k}'s rows are not its video's frames in order")
    want = grid_keep(idx[:, 0], rec["spans"], step)
    keep = np.isin(rows[:, 0], want)
    if int(keep.sum()) != len(want):
        raise ValueError(f"{sid}: the stored {roi} rows miss {len(want) - int(keep.sum())} "
                         f"grid times")
    dst.mkdir(parents=True, exist_ok=True)
    video, out = src / f"{sid}.r{k}.mkv", dst / f"{sid}.r{k}.mkv"
    x0, y0, x1, y1 = rec["rects"][k]
    n_in = 0
    part = out.with_suffix(".part.mkv")
    proc = subprocess.Popen(ffv1_command(ffmpeg_path(), x1 - x0, y1 - y0, rec["hz"], part,
                                         threads=1), stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(str(video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    try:
        while True:
            ok, crop = cap.read()
            if not ok:
                break
            if n_in < len(keep) and keep[n_in]:
                proc.stdin.write(np.ascontiguousarray(crop).tobytes())
            n_in += 1
    finally:
        cap.release()
        proc.stdin.close()
        code = proc.wait()
    if code != 0 or n_in != len(rows):
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{sid}: decoded {n_in} of {len(rows)} cached {roi} frames, "
                           f"ffmpeg exit {code}")
    part.replace(out)
    kept = rows[keep].copy()
    kept[:, 3] = np.arange(len(kept))
    new_idx = np.concatenate([idx[idx[:, 2] != k], kept])
    new_idx = new_idx[np.lexsort((new_idx[:, 2], new_idx[:, 0]))]
    np.save(dst / f"{sid}.idx.npy", new_idx)
    size, before = int(out.stat().st_size), int(video.stat().st_size)
    record = {**rec, "thinned_rois": {**(rec.get("thinned_rois") or {}), roi: {
        "version": GRID_THIN_VERSION, "rule": "grid_keep", "step_s": step, "spans": "record",
        "frames_kept": int(keep.sum()), "frames_set": int(len(np.unique(idx[:, 0]))),
        "by": tool, "frames_before": int(len(rows)), "bytes_before": before,
        "bytes_after": size}}}
    if rec.get("bytes") is not None:
        record["bytes"] = int(rec["bytes"]) - before + size
    (dst / f"{sid}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"rect": k, "frames_before": int(len(rows)), "frames_kept": int(keep.sum()),
            "frames_decoded": n_in, "bytes_before": before, "bytes_after": size}
