"""Readers that ride one decode, and the session context they share.

Decode is the cost of this pipeline. Measured 2026-09-05 on c40d950031bb: 300
sampled frames take 13.17 s to decode and 0.94 s to run the scoreline, bottom
HUD and killfeed extractors over -- 93% and 7%. For the minimap at 15 Hz the
split is 66/34, because ring fitting is real work, but decode still dominates.
So the question that decides how long anything here takes is not how fast a
reader is, it is **how many times the file is opened**.

Before `decode.sample_multi` there was no way to express "run alongside a pass
that is already happening", so every stage and every prototype opened the file
for itself: `hud`, `minimap`, `xmark_eval`, `chokepoint_eval`, `ping_scan`,
`reader_census`. Fusing just the two shipped stages saved 45%. This module is
the other half -- a reader is an object with a rate, a span filter and a
`feed`, so a probe can join a scan instead of costing another full decode.

**Deliberately thin, and it stays that way.** It owns no analysis, decides
nothing about what a reader does with a frame, and every reader here can still
be driven by an ordinary loop -- which is what keeps `hud` and `minimap` honest
as standalone commands. What it centralises is the SESSION CONTEXT: the
manifest, the profile, the ROIs, and the two per-session constants that cost
seeks to derive (the killfeed overlay mask, the minimap static map). Those were
being rebuilt independently by five callers, which is the same duplication in a
different costume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np


class Reader(Protocol):
    """What `run` needs of a reader. `hz` and `spans` decide which frames.

    **`finish` is part of the contract, not an extra.** It was left out of the
    first version and that is a way for a reader to be silently inert: a
    two-phase reader like `ping.PingReader` has no results at all until it is
    called, while `_HudPass` and `_MinimapPass` accumulate into `.rows` and need
    nothing. A fourth reader of the first kind, added to a `readers` list, would
    have been fed every frame and produced nothing, with no error anywhere.
    `run` now calls it on every reader that has one, so the failure cannot
    happen -- and calling it twice is not an error, because the two-phase
    readers here are idempotent by construction (`finish` recomputes from
    accumulated state rather than consuming it).
    """

    name: str
    hz: float
    spans: list[tuple[float, float]] | None

    def feed(self, sample) -> None: ...


@dataclass
class SessionContext:
    """Everything a reader needs about a session, derived at most once.

    The two cached fields are the point. `kf_mask` costs 40 seeks and
    `static_map` costs 120; between them they were being paid separately by the
    shipped stages and by every prototype that touched the same session.
    """

    store: object
    manifest: dict
    profile: object
    spans: list[tuple[float, float]] = field(default_factory=list)

    @property
    def src(self) -> dict:
        return self.manifest["source"]

    @property
    def session_id(self) -> str:
        return self.manifest["session_id"]

    @property
    def wh(self) -> tuple[int, int]:
        return int(self.src["width"]), int(self.src["height"])

    @property
    def fps(self) -> float:
        return float(self.src["fps"])

    @property
    def media(self) -> Path:
        p = Path(self.src["path"])
        if not p.is_file():
            raise SystemExit(
                f"source media has moved: {p}\n"
                "the manifest records where it was at ingest time"
            )
        return p

    def kf_mask(self):
        """The killfeed overlay mask, from cache or measured once."""
        from .killfeed import killfeed_roi, overlay_mask

        import cv2

        got = self.store.read_kf_mask(self.session_id)
        if got is not None:
            return got
        roi = killfeed_roi(self.profile)
        if roi is None:
            return None
        w, h = self.wh
        cap = cv2.VideoCapture(str(self.media))
        cal = []
        try:
            dur = int(self.src["duration_ms"] or 0)
            step = max(1, dur // 40)
            for ms in range(0, dur, step):
                cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                ok, fr = cap.read()
                if ok:
                    cal.append(fr)
        finally:
            cap.release()
        if not cal:
            return None
        m = overlay_mask(cal, roi, w, h)
        self.store.write_kf_mask(self.session_id, m)
        return m

    def static_map(self):
        """The minimap's per-pixel median, from cache or measured once."""
        from .minimap import minimap_roi_px, static_map as _static

        import cv2

        got = self.store.read_static_map(self.session_id)
        if got is not None:
            return got
        if not self.spans:
            raise SystemExit(
                "the static map is built from ACTIVE SPANS -- "
                "run `reticle segment` first, or pass spans"
            )
        w, h = self.wh
        cap = cv2.VideoCapture(str(self.media))
        try:
            med = _static(cap, self.fps, self.spans, minimap_roi_px(self.profile, w, h))
        finally:
            cap.release()
        self.store.write_static_map(self.session_id, med)
        return med

    def floor(self) -> np.ndarray:
        from .minimap import floor_mask

        return floor_mask(self.static_map())

    def sgray(self) -> np.ndarray:
        import cv2

        return cv2.cvtColor(self.static_map(), cv2.COLOR_BGR2GRAY).astype(np.float64)


def run(ctx: SessionContext, readers: list, progress=None) -> int:
    """Drive every reader over ONE decode. Returns frames retrieved.

    A reader is fed only the frames it asked for -- `decode.sample_multi`
    decides that from each one's `hz` and `spans` -- so adding a slow reader
    over a narrow window costs that window, not another pass over the file.
    """
    from .decode import sample_multi

    req = {r.name: (r.hz, r.spans) for r in readers}
    by_name = {r.name: r for r in readers}
    n = 0
    for who, smp in sample_multi(str(ctx.media), ctx.fps, req):
        n += 1
        for name in who:
            by_name[name].feed(smp)
        if progress is not None:
            progress(n, smp)
    for r in readers:
        fin = getattr(r, "finish", None)
        if callable(fin):
            fin()
    return n
