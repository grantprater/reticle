"""Play a round with only its stored events drawn over it: an event consumer.

    reticle view SESSION --round N [--start S] [--seconds S]
    reticle view SESSION --gaps

The pipeline emits events, and a consumer reads those events and nothing else.
This viewer is that consumer. The round's window comes from the stored rounds;
the source video is only the backdrop; every drawn thing is an `Item` that
`view_events` built from one stored row. The viewer calls no reader, tracker
or adjudicator and decides nothing. Where a stream lacks a field -- a facing,
a position, a name -- the viewer draws the absence, and `--gaps` lists it
against the stream's owner. `overlay` is the other kind of tool: it reruns the
readers on each frame to debug them.

Colour follows `overlay`: amber is a refusal, abstention or unread value, drawn
with its stored reason; it is never a negative. A dimmer ring with `?` is a
stored ambiguity (alternatives or a provisional identity).

Controls (the labelling-pass layout where it applies):

    space         play / pause           A / D     one frame back / forward
    left / right  1 s back / forward     up / down 5 s forward / back
    home          round start            1-7       toggle a layer; 0 all on
    M             mark "wrong here": pauses, click to point (optional), then a
                  layer key 1-7, or U when unsure which layer; Esc cancels
    right-click   retract the last mark  S         sound on / off
    P             save a screenshot      H         help
    Z             magnified minimap on / off
    Q / Esc       quit                   click the time strip to seek

A mark is one appended row in `<store>/labels/round_review/<sid>.jsonl`:
the time, the layer, the click, and the layer's nearest stored event with its
id and version. The file is created by the first mark and never seeded.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import view_events as ve
from .profiles import get_profile
from .widget_frame import capture_box, is_variant

ROUND_VIEW_VERSION = "round-view-0.1.0"

# BGR, the overlay's palette where the meaning is the same.
INK = (236, 233, 230)
DIM = (120, 116, 112)
PANEL = (28, 24, 22)
AMBER = (60, 180, 245)
COLOURS = {
    "ink": INK, "self": (90, 230, 250), "ally": (150, 230, 130), "barrier": (170, 150, 140),
    "cone": (235, 180, 80), "kill": (120, 220, 130), "death": (90, 95, 235),
    "ability": (230, 140, 220), "smoke": (200, 200, 200), "spike": (255, 160, 70),
    "ping": (255, 255, 120), "mark": (200, 90, 200),
}
LAYER_COLOUR = {"round_entity": COLOURS["ally"], "team_vision": COLOURS["cone"],
                "death": COLOURS["death"], "ability": COLOURS["ability"],
                "spike": COLOURS["spike"], "ping": COLOURS["ping"], "killfeed": INK}
FONT = cv2.FONT_HERSHEY_SIMPLEX
STRIP_H = 56
BELOW_NORMAL = 0x00004000
CREATE_NO_WINDOW = 0x08000000


def lower_to_below_normal() -> None:
    """Lower this process to Below Normal; the viewer shares the CPU."""
    if os.name != "nt":
        return
    import ctypes
    k = ctypes.windll.kernel32
    k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL)


# ------------------------------------------------------------ the backdrop

class FrameSource:
    """Frames of the source video, GPU-decoded where PyAV has CUDA.

    The backdrop only: nothing reads these pixels. `t_ms` is presentation
    time less the stream start, the store's time base."""

    def __init__(self, path: str, gpu: bool = True):
        import av

        self.path = path
        self.backend = "cpu"
        self._c = None
        if gpu:
            try:
                from av.codec.hwaccel import HWAccel
                self._c = av.open(path, hwaccel=HWAccel("cuda", allow_software_fallback=False,
                                                        is_hw_owned=True))
                self.backend = "nvdec"
            except Exception as exc:          # no CUDA: decode on the CPU
                self.fallback = f"{type(exc).__name__}: {exc}"
                self._c = None
        if self._c is None:
            self._c = av.open(path)
            self._c.streams.video[0].codec_context.thread_count = 2
        self.vs = self._c.streams.video[0]
        self.tb = float(self.vs.time_base)
        self.start = self.vs.start_time or 0
        rate = self.vs.average_rate
        self.fps = float(rate) if rate else 60.0
        self._it = None
        self._peek = None

    def _frames(self):
        import av
        for packet in self._c.demux(self.vs):
            try:
                yield from packet.decode()
            except av.error.InvalidDataError:
                continue

    def t_of(self, frame) -> float:
        return 0.0 if frame.pts is None else (frame.pts - self.start) * self.tb * 1000.0

    def seek(self, t_ms: float):
        """Decode to the first frame at or after `t_ms`; returns it."""
        pts = int(max(0.0, t_ms - 1500.0) / 1000.0 / self.tb) + self.start
        self._c.seek(pts, stream=self.vs, backward=True, any_frame=False)
        self._it = self._frames()
        self._peek = None
        half = 500.0 / self.fps
        while True:
            f = self.next()
            if f is None or self.t_of(f) >= t_ms - half:
                return f

    def next(self):
        if self._peek is not None:
            f, self._peek = self._peek, None
            return f
        if self._it is None:
            self._it = self._frames()
        return next(self._it, None)

    def peek_t(self) -> float | None:
        if self._peek is None:
            self._peek = self.next()
        return None if self._peek is None else self.t_of(self._peek)

    def bgr(self, frame) -> np.ndarray:
        if frame.format.name == "cuda":
            nv12 = frame.reformat(format="nv12").to_ndarray()
            return cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
        return frame.to_ndarray(format="bgr24")

    def close(self):
        self._c.close()


# --------------------------------------------------------------- geometry

@dataclass
class Geometry:
    """Where each drawing space sits in the frame (capture layout, not map)."""

    width: int
    height: int
    minimap: tuple        # x0, y0, x1, y1
    killfeed: tuple | None
    variant: bool = False

    @classmethod
    def of(cls, manifest: dict) -> "Geometry":
        src = manifest["source"]
        w, h = int(src["width"]), int(src["height"])
        prof = get_profile(manifest["source_profile"])
        rois = {r.name: r.pixels(w, h) for r in prof.rois}
        box = capture_box(manifest) or rois["minimap"]
        return cls(w, h, tuple(box), rois.get("killfeed"), is_variant(manifest))

    def to_frame(self, it: ve.Item):
        """An item's point in frame pixels, or None for a panel item."""
        if it.space == "minimap" and it.x is not None and it.y is not None:
            return (self.minimap[0] + it.x, self.minimap[1] + it.y)
        if it.space == "killfeed" and self.killfeed is not None and it.box:
            x0, y0, x1, y1 = it.box
            kx0, ky0, kx1, _ = self.killfeed
            xa = kx0 + (x0 if x0 is not None else 0)
            xb = kx0 + (x1 if x1 is not None else kx1 - kx0)
            return ((xa + xb) / 2, ky0 + ((y0 or 0) + (y1 or 0)) / 2)
        return None


# ------------------------------------------------------------------ marks

class Marks:
    """Append-only marks; the file appears with the first mark, never before."""

    def __init__(self, path: Path, session_id: str):
        self.path, self.sid = Path(path), session_id
        self.rows = []
        if self.path.is_file():
            with open(self.path, encoding="utf-8") as f:
                self.rows = [json.loads(ln) for ln in f if ln.strip()]
        self.mine = []

    def _append(self, row: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
        self.rows.append(row)
        return row

    def mark(self, t_ms: float, layer: str, loaded: ve.Loaded, geo: Geometry,
             point=None, visible=(), round_no=None) -> dict:
        near = (None if layer == "unsure" else
                ve.nearest_event(loaded, layer, t_ms, point, geo.to_frame))
        row = {"kind": "wrong_here", "mark_id": uuid.uuid4().hex[:12],
               "session_id": self.sid, "round_no": round_no, "t_ms": round(t_ms, 1),
               "layer": layer, "unsure": layer == "unsure",
               "point": None if point is None else {"x": round(point[0], 1),
                                                    "y": round(point[1], 1),
                                                    "space": "frame"},
               "nearest": near,
               "nearest_reason": None if near else (
                   "layer not chosen" if layer == "unsure" else "the layer has no stored "
                   "event in this window"),
               "visible_layers": sorted(visible), "by": "player",
               "viewer_version": ROUND_VIEW_VERSION,
               "view_events_version": ve.VIEW_EVENTS_VERSION,
               "marked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
        self.mine.append(row["mark_id"])
        return self._append(row)

    def retract_last(self) -> dict | None:
        if not self.mine:
            return None
        mid = self.mine.pop()
        return self._append({"kind": "retract", "mark_id": mid, "session_id": self.sid,
                             "by": "player", "viewer_version": ROUND_VIEW_VERSION,
                             "marked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(
                                 timespec="seconds")})

    def live(self) -> list[dict]:
        gone = {r["mark_id"] for r in self.rows if r.get("kind") == "retract"}
        return [r for r in self.rows if r.get("kind") == "wrong_here"
                and r["mark_id"] not in gone]


# ---------------------------------------------------------------- drawing

@dataclass
class ViewState:
    t_ms: float = 0.0
    playing: bool = False
    layers: set = field(default_factory=lambda: {n for _k, n, _s in ve.LAYERS})
    mark: dict | None = None          # {"t": ms, "point": (x, y) | None}
    audio: str = "off"
    help: bool = False
    inset: bool = True
    message: str = ""
    backend: str = ""


def _text(img, s, org, colour=INK, scale=0.5, weight=1):
    """Text with a dark outline. The outline is the same stroke drawn at
    offsets: OpenCV 5 widens a thicker stroke's advance, so a thick black
    pass would run past the coloured one."""
    x, y = int(org[0]), int(org[1])
    for dx, dy in ((-1, -1), (1, 1), (-1, 1), (1, -1)):
        cv2.putText(img, s, (x + dx, y + dy), FONT, scale, (0, 0, 0), weight, cv2.LINE_AA)
    cv2.putText(img, s, (x, y), FONT, scale, colour, weight, cv2.LINE_AA)


def _panel(img, x, y, w, h, alpha=0.62):
    x, y = max(0, int(x)), max(0, int(y))
    sub = img[y:y + int(h), x:x + int(w)]
    if sub.size:
        sub[:] = cv2.addWeighted(sub, 1 - alpha, np.full_like(sub, PANEL), alpha, 0)


def _colour(it: ve.Item):
    return AMBER if it.status in ve.NOT_READ else COLOURS.get(it.colour, INK)


def _short(s, n=46):
    s = str(s)
    return s if len(s) <= n else s[:n - 3] + "..."


def _p(geo, it):
    p = geo.to_frame(it)
    return None if p is None else (int(round(p[0])), int(round(p[1])))


#: The magnified minimap: its scale, and where it sits (bottom right, clear
#: of the killfeed and the crosshair).
INSET_K = 2


def _draw_cones(img, geo, items):
    for it in items:
        if it.mask is None:
            continue
        m = ve.unpack_mask(it.mask)
        x0, y0 = geo.minimap[0], geo.minimap[1]
        h = min(m.shape[0], img.shape[0] - y0)
        w = min(m.shape[1], img.shape[1] - x0)
        sub = img[y0:y0 + h, x0:x0 + w]
        tint = np.empty_like(sub)
        tint[:] = COLOURS["cone"]
        mm = m[:h, :w, None]
        sub[:] = np.where(mm, cv2.addWeighted(sub, 0.66, tint, 0.34, 0), sub)


def _draw_minimap_item(img, it: ve.Item, ox: float, oy: float, k: float = 1.0,
                       labels: bool = True):
    """One minimap item, its widget position mapped by `(ox + k x, oy + k y)`."""
    if it.x is None or it.y is None:
        return
    p = (int(round(ox + k * it.x)), int(round(oy + k * it.y)))
    c = _colour(it)
    if not labels:
        if it.stream in ("ability_shape", "smoke"):
            cv2.circle(img, p, int(round(k * (it.r or 8))), c, 1, cv2.LINE_AA)
        else:
            cv2.circle(img, p, 3, c, -1, cv2.LINE_AA)
        return
    if it.stream == "team_vision":
        cv2.circle(img, p, int(7 * k), c, 1, cv2.LINE_AA)
        if it.facing is not None:
            th = np.radians(it.facing)
            tip = (int(p[0] + 14 * k * np.cos(th)), int(p[1] + 14 * k * np.sin(th)))
            cv2.arrowedLine(img, p, tip, c, 2, cv2.LINE_AA, tipLength=0.35)
        else:
            _text(img, "?", (p[0] - 16, p[1] - 6), AMBER, 0.45)
        _text(img, it.label, (p[0] - 34, p[1] - 10), c, 0.38)
    elif it.stream == "round_entity":
        cv2.circle(img, p, int(10 * k), c, 1 if it.status == "uncertain" else 2, cv2.LINE_AA)
        label = it.label + ("?" if it.status == "uncertain" else "")
        if it.status in ve.NOT_READ and it.reason:
            label += f" [{_short(it.reason, 22)}]"
        _text(img, label, (p[0] + 10 * k + 2, p[1] + 14), c, 0.45)
    elif it.stream in ("ability_shape", "smoke"):
        r = int(round(k * (it.r or 8)))
        if it.stream == "smoke":
            y0, y1 = max(0, p[1] - r - 1), min(img.shape[0], p[1] + r + 2)
            x0, x1 = max(0, p[0] - r - 1), min(img.shape[1], p[0] + r + 2)
            sub = img[y0:y1, x0:x1]
            if sub.size:
                ov = sub.copy()
                cv2.circle(ov, (p[0] - x0, p[1] - y0), r, c, -1, cv2.LINE_AA)
                sub[:] = cv2.addWeighted(sub, 0.7, ov, 0.3, 0)
        cv2.circle(img, p, r, c, 2, cv2.LINE_AA)
        _text(img, _short(it.label, 30), (p[0] - r, p[1] - r - 4), c, 0.4)
    elif it.stream == "spike":
        d = 8
        pts = np.array([(p[0], p[1] - d), (p[0] + d, p[1]), (p[0], p[1] + d),
                        (p[0] - d, p[1])], np.int32)
        cv2.polylines(img, [pts], True, c, 2, cv2.LINE_AA)
        lab = it.label + (f" [{it.reason}]" if it.reason else "")
        _text(img, lab, (p[0] + 10, p[1] - 8), c, 0.4)
    elif it.stream == "ping":
        cv2.drawMarker(img, p, c, cv2.MARKER_TILTED_CROSS, 14, 2, cv2.LINE_AA)
        _text(img, it.label, (p[0] + 9, p[1] + 16), c, 0.4)


def _draw_killfeed(img, geo, items):
    if geo.killfeed is None:
        return
    kx0, ky0, kx1, _ky1 = geo.killfeed
    by_band = {}
    for it in items:
        x0, y0, x1, y1 = it.box
        c = _colour(it)
        xa = kx0 + (x0 if x0 is not None else 0)
        xb = kx0 + (x1 if x1 is not None else kx1 - kx0)
        cv2.rectangle(img, (int(xa), int(ky0 + y0)), (int(xb), int(ky0 + y1)), c,
                      1 if it.stream == "killfeed_name" else 2)
        band = int(y0)
        txt = it.label + (f" [{_short(it.reason, 18)}]" if it.reason else "")
        by_band.setdefault(band, []).append((txt, c, int(ky0 + y1)))
    for band, parts in sorted(by_band.items()):
        x = kx0 - 8
        y = ky0 + band + 16
        for txt, c, _ in reversed(parts):
            (tw, _th), _ = cv2.getTextSize(txt, FONT, 0.42, 1)
            x -= tw + 12
            _text(img, txt, (x, y), c, 0.42)


def _panel_lines(loaded, state, t):
    """Per visible layer, the text lines its active items draw in the panel."""
    out = []
    for key, layer, streams in ve.LAYERS:
        if layer not in state.layers:
            continue
        lines = []
        for s in streams:
            for it in loaded.active(s, t):
                if s == "round_entity":
                    alts = it.detail.get("alternatives") or []
                    txt = (f"{it.label}  {it.detail.get('identity_status')}  "
                           f"{(it.entity_id or 'no entity').split(':')[-1]}")
                    if alts:
                        txt += "  alt " + ",".join(a.split(":")[-1] for a in alts[:3])
                    if it.reason:
                        txt += f"  -- {it.reason}"
                    lines.append((txt, _colour(it)))
                elif s == "team_vision":
                    if it.row_kind == "frame" and it.mask is not None:
                        d = it.detail
                        lines.append((f"observable {d.get('observable_px')} px of widget "
                                      f"{d.get('widget_px')}", COLOURS["cone"]))
                    elif it.row_kind == "frame":
                        lines.append((f"{it.label} -- {it.reason}", AMBER))
                    elif it.status != "ok":
                        lines.append((f"{it.label}: {it.reason}", _colour(it)))
                elif it.space == "panel" or s in ("smoke", "ability_shape"):
                    txt = it.label
                    if it.reason and it.status != "ok":
                        txt += f"  -- {it.reason}"
                    lines.append((txt, _colour(it)))
                    if s == "death":
                        lines.append(("    id: " + it.detail.get("identity", ""), DIM))
        for s in streams:
            if loaded.presence.get(s) == "no stream for this session":
                lines.append((f"{s}: no stream for this session", DIM))
        out.append((key, layer, lines))
    return out


def render(frame: np.ndarray, t: float, loaded: ve.Loaded, geo: Geometry,
           state: ViewState, marks: list[dict] | None = None) -> np.ndarray:
    """The frame with every visible layer's active items, and the time strip."""
    img = frame.copy()
    H, W = img.shape[:2]
    on = state.layers
    if "team_vision" in on:
        _draw_cones(img, geo, loaded.active("team_vision", t))
    mx0, my0, mx1, my1 = geo.minimap
    mm_items = [it for layer in ("ability", "ping", "spike", "team_vision", "round_entity")
                if layer in on
                for s in next(st for _k, n, st in ve.LAYERS if n == layer)
                for it in loaded.active(s, t) if it.space == "minimap"]
    inset = None
    if state.inset:
        crop = img[my0:my1, mx0:mx1]
        inset = cv2.resize(crop, None, fx=INSET_K, fy=INSET_K, interpolation=cv2.INTER_LINEAR)
        for it in mm_items:
            _draw_minimap_item(inset, it, 0, 0, INSET_K)
    for it in mm_items:
        _draw_minimap_item(img, it, mx0, my0, 1.0, labels=inset is None)
    if "killfeed" in on:
        kf = [it for s in ("killfeed_name", "killfeed_portrait", "killfeed_weapon")
              for it in loaded.active(s, t)]
        _draw_killfeed(img, geo, kf)
    cv2.rectangle(img, (mx0, my0), (mx1, my1), DIM, 1)
    if inset is not None:
        ih, iw = inset.shape[:2]
        ix, iy = W - iw - 16, H - ih - 150
        img[iy:iy + ih, ix:ix + iw] = inset
        cv2.rectangle(img, (ix - 1, iy - 1), (ix + iw, iy + ih), DIM, 1)
        _text(img, f"minimap x{INSET_K} (Z hides)", (ix + 6, iy + 20), DIM, 0.5)
    if state.mark and state.mark.get("point"):
        px, py = map(int, state.mark["point"])
        cv2.drawMarker(img, (px, py), COLOURS["mark"], cv2.MARKER_CROSS, 28, 2)

    # ---- the panel, under the minimap
    y = my1 + 12
    x = 12
    rows = _panel_lines(loaded, state, t)
    n = sum(1 + min(len(ls), 9) for _k, _l, ls in rows)
    _panel(img, x - 4, y - 2, 640, 20 * n + 12)
    y += 16
    for key, layer, lines in rows:
        _text(img, f"{key} {layer}", (x, y), LAYER_COLOUR[layer], 0.5, 1)
        y += 20
        for txt, c in lines[:8]:
            _text(img, _short(txt, 78), (x + 14, y), c, 0.44)
            y += 20
        if len(lines) > 8:
            _text(img, f"... {len(lines) - 8} more", (x + 14, y), DIM, 0.42)
            y += 20

    # ---- the header
    r = loaded.round or {}
    t0 = r.get("t_start_ms", loaded.t0)
    head = (f"{loaded.session_id}  R{r.get('round_no', '?')}  t {ve._hms(t)}  "
            f"(+{(t - t0) / 1000:.1f} s)  {'PLAYING' if state.playing else 'PAUSED'}"
            f"  audio {state.audio}  {state.backend}")
    if geo.variant:
        head += "  VARIANT WIDGET: positions drawn without its placement"
    (tw, _), _ = cv2.getTextSize(head, FONT, 0.55, 1)
    _panel(img, W // 2 - tw // 2 - 10, 4, tw + 20, 30)
    _text(img, head, (W // 2 - tw // 2, 25), INK, 0.55)
    msg = state.message
    if state.mark:
        msg = (f"MARK at {ve._hms(state.mark['t'])}: click to point (optional), then a layer "
               f"1-7, or U if unsure which; Esc cancels")
    if msg:
        (tw, _), _ = cv2.getTextSize(msg, FONT, 0.55, 1)
        _panel(img, W // 2 - tw // 2 - 10, 38, tw + 20, 28)
        _text(img, msg, (W // 2 - tw // 2, 58), COLOURS["mark"] if state.mark else AMBER, 0.55)
    if state.help:
        _draw_help(img)
    return np.vstack([img, _timeline_strip(W, t, loaded, state, marks or [])])


def _draw_help(img):
    doc = (__doc__ or "").split("Controls")[1].split("A mark is")[0].strip("\n: ").splitlines()
    H, W = img.shape[:2]
    _panel(img, W // 2 - 420, 120, 840, 24 * len(doc) + 30, alpha=0.85)
    for i, ln in enumerate(doc):
        _text(img, ln.rstrip(), (W // 2 - 400, 150 + 24 * i), INK, 0.52)


def strip_span(loaded):
    r = loaded.round or {}
    return float(r.get("t_start_ms", loaded.t0)), float(r.get("t_close_ms") or loaded.t1)


def _timeline_strip(W, t, loaded, state, marks):
    s = np.full((STRIP_H, W, 3), PANEL, np.uint8)
    a, z = strip_span(loaded)
    x0, x1 = 90, W - 20

    def xt(tt):
        return int(x0 + (x1 - x0) * (min(max(tt, a), z) - a) / max(1.0, z - a))

    cv2.rectangle(s, (x0, 8), (x1, 22), DIM, 1)
    cv2.rectangle(s, (xt(loaded.t0), 9), (xt(loaded.t1), 21), (70, 66, 62), -1)
    for it in loaded.items.get("death", []):
        c = COLOURS["death"] if "YOU" in it.label else INK
        cv2.line(s, (xt(it.t_ms), 6), (xt(it.t_ms), 24), c, 2)
    for it in loaded.items.get("ult_cast", []):
        cv2.line(s, (xt(it.t_ms), 22), (xt(it.t_ms), 28), COLOURS["ability"], 2)
    for it in loaded.items.get("ping", []):
        cv2.line(s, (xt(it.t_ms), 2), (xt(it.t_ms), 8), COLOURS["ping"], 2)
    for m in marks:
        if a <= m["t_ms"] <= z:
            cv2.drawMarker(s, (xt(m["t_ms"]), 15), COLOURS["mark"], cv2.MARKER_TRIANGLE_DOWN,
                           10, 2)
    cv2.line(s, (xt(t), 2), (xt(t), 28), (255, 255, 255), 2)
    _text(s, f"{(t - a) / 1000:6.1f}s", (8, 20), INK, 0.48)
    x = 8
    for key, layer, _st in ve.LAYERS:
        c = LAYER_COLOUR[layer] if layer in state.layers else DIM
        txt = f"{key} {layer}" + ("" if layer in state.layers else " (off)")
        _text(s, txt, (x, 47), c, 0.46)
        x += cv2.getTextSize(txt, FONT, 0.46, 1)[0][0] + 22
    _text(s, "amber = refused / abstained / unread, with its reason (not a negative)   "
             "M mark   H help", (x + 10, 47), AMBER, 0.44)
    return s


def strip_time(loaded, W, x) -> float:
    a, z = strip_span(loaded)
    x0, x1 = 90, W - 20
    return a + (z - a) * min(max((x - x0) / (x1 - x0), 0.0), 1.0)


# ------------------------------------------------------------------ audio

class Audio:
    """The capture's sound through `ffplay`, restarted at each play or seek."""

    def __init__(self, path: str, enabled: bool = True, volume: int = 100):
        self.path, self.volume = path, int(volume)
        self.exe = shutil.which("ffplay")
        self.enabled = enabled and self.exe is not None
        self.proc = None

    @property
    def status(self) -> str:
        if self.exe is None:
            return "unavailable (no ffplay on PATH)"
        return "on" if self.enabled else "off"

    def play(self, t_ms: float):
        self.stop()
        if not self.enabled:
            return
        flags = (BELOW_NORMAL | CREATE_NO_WINDOW) if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [self.exe, "-nodisp", "-vn", "-sn", "-autoexit", "-loglevel", "quiet",
             "-volume", str(self.volume),
             "-ss", f"{t_ms / 1000.0:.3f}", self.path],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)

    def stop(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=5)
            self.proc = None


# -------------------------------------------------------------- the player

class GdiBlit:
    """Paint a BGR image straight onto a Tk widget's window with GDI.

    Tk's photo image costs 40 ms a frame at 1440x852 and 74 ms at 1920x1136
    (measured here, 2026-09-30), which caps playback near 15 frames/s.
    `StretchDIBits` paints the same pixels in a few milliseconds. Windows
    only; elsewhere the viewer falls back to a photo image."""

    def __init__(self, hwnd: int):
        import ctypes
        from ctypes import wintypes

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        self.ct, self.BIH, self.hwnd = ctypes, BIH, wintypes.HWND(hwnd)
        self.user32, self.gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi32.StretchDIBits.argtypes = [wintypes.HDC] + [ctypes.c_int] * 8 + [
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]

    def paint(self, bgr: np.ndarray) -> bool:
        h, w = bgr.shape[:2]
        if (w * 3) % 4:                       # DIB rows are 4-byte aligned
            bgr = np.ascontiguousarray(bgr[:, : w - w % 4])
            w = bgr.shape[1]
        bgr = np.ascontiguousarray(bgr)
        bih = self.BIH(ctypes_size(self.BIH), w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
        hdc = self.user32.GetDC(self.hwnd)
        try:
            n = self.gdi32.StretchDIBits(hdc, 0, 0, w, h, 0, 0, w, h,
                                         bgr.ctypes.data, self.ct.byref(bih), 0, 0x00CC0020)
        finally:
            self.user32.ReleaseDC(self.hwnd, hdc)
        return n != 0


def ctypes_size(t) -> int:
    import ctypes
    return ctypes.sizeof(t)


class Player:
    """The Tk window: playback, toggles, marks. Holds no rule of its own."""

    def __init__(self, src: FrameSource, loaded: ve.Loaded, geo: Geometry, marks: Marks,
                 audio: Audio, shots: Path, scale: float | None = None,
                 quit_after_s: float | None = None, autoplay: bool = False):
        import tkinter as tk

        self.tk = tk
        self.src, self.loaded, self.geo, self.marks = src, loaded, geo, marks
        self.audio, self.shots = audio, shots
        self.state = ViewState(t_ms=loaded.t0, audio=audio.status, backend=src.backend)
        self.root = tk.Tk()
        self.root.title(f"reticle view {loaded.session_id} R{(loaded.round or {}).get('round_no')}")
        sh = self.root.winfo_screenheight()
        full_h = geo.height + STRIP_H
        self.scale = scale or min(1.0, (sh - 110) / full_h)
        self.cw, self.ch = int(geo.width * self.scale), int(full_h * self.scale)
        self.canvas = tk.Canvas(self.root, width=self.cw, height=self.ch, highlightthickness=0,
                                bg="black")
        self.canvas.pack()
        self.photo = None
        self.image_id = None
        self.blit = None
        if os.name == "nt":
            self.root.update()
            try:
                self.blit = GdiBlit(self.canvas.winfo_id())
            except Exception:                # no GDI: a photo image, slower
                self.blit = None
            self.canvas.bind("<Expose>", lambda e: self.root.after_idle(self.repaint))
        self.frame = None
        self.frame_t = loaded.t0
        self.wall0 = self.media0 = 0.0
        self.shown = 0
        self.shown_since = time.perf_counter()
        self.quit_after_s = quit_after_s
        self.opened = time.perf_counter()
        for seq, fn in (("<space>", self.toggle_play), ("<Left>", lambda e: self.jump(-1000)),
                        ("<Right>", lambda e: self.jump(1000)),
                        ("<Up>", lambda e: self.jump(5000)),
                        ("<Down>", lambda e: self.jump(-5000)),
                        ("<Home>", lambda e: self.seek(self.loaded.t0)),
                        ("<Key>", self.key), ("<Button-1>", self.click),
                        ("<Button-3>", self.retract), ("<Escape>", self.escape)):
            self.root.bind(seq, fn)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.seek(loaded.t0)
        if autoplay:
            self.toggle_play()
        self.root.after(15, self.tick)

    # -- display
    def show(self):
        img = render(self.frame_img, self.frame_t, self.loaded, self.geo, self.state,
                     self.marks.live())
        self.last_render = img
        if self.scale != 1.0:
            img = cv2.resize(img, (self.cw, self.ch), interpolation=cv2.INTER_LINEAR)
        self.last_shown = img
        self.shown += 1
        if self.blit is not None and self.blit.paint(img):
            return
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ppm = b"P6 %d %d 255\n" % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()
        self.photo = self.tk.PhotoImage(data=ppm, format="PPM")
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        else:
            self.canvas.itemconfigure(self.image_id, image=self.photo)

    def repaint(self):
        if self.blit is not None and getattr(self, "last_shown", None) is not None:
            self.blit.paint(self.last_shown)

    def set_frame(self, f):
        if f is None:
            return False
        self.frame_t = self.src.t_of(f)
        self.frame_img = self.src.bgr(f)
        self.state.t_ms = self.frame_t
        return True

    # -- time
    def seek(self, t: float):
        t = min(max(t, self.loaded.t0), self.loaded.t1)
        self.set_frame(self.src.seek(t))
        if self.state.playing:
            self.wall0, self.media0 = time.perf_counter(), self.frame_t
            self.audio.play(self.frame_t)
        self.show()

    def jump(self, dt):
        self.seek(self.frame_t + dt)

    def step(self, n: int):
        self.pause()
        if n > 0:
            self.set_frame(self.src.next())
            self.show()
        else:
            self.seek(self.frame_t - 1000.0 / self.src.fps)

    def toggle_play(self, _e=None):
        if self.state.mark:
            return
        if self.state.playing:
            self.pause()
        else:
            if self.frame_t >= self.loaded.t1 - 50:
                self.set_frame(self.src.seek(self.loaded.t0))
            self.state.playing = True
            self.wall0, self.media0 = time.perf_counter(), self.frame_t
            self.audio.play(self.frame_t)
            self.shown, self.shown_since = 0, time.perf_counter()
        self.show()

    def pause(self):
        if self.state.playing:
            self.state.playing = False
            self.audio.stop()
            self.show()

    def tick(self):
        delay = 30
        if self.quit_after_s and time.perf_counter() - self.opened > self.quit_after_s:
            self.fps_at_quit = self.fps_shown()
            self.audio_ran = self.audio.proc is not None and self.audio.proc.poll() is None
            print(f"wrote {self.screenshot()}")
            self.quit()
            return
        if self.state.playing:
            target = self.media0 + (time.perf_counter() - self.wall0) * 1000.0
            last = None
            while True:
                nt = self.src.peek_t()
                if nt is None or nt > target:
                    break
                last = self.src.next()
            if last is not None:
                self.set_frame(last)
                self.show()
            if self.frame_t >= self.loaded.t1 or self.src.peek_t() is None:
                self.pause()
            else:
                nt = self.src.peek_t()
                now = self.media0 + (time.perf_counter() - self.wall0) * 1000.0
                delay = max(1, int(nt - now))
        self.root.after(delay, self.tick)

    def fps_shown(self) -> float:
        dt = time.perf_counter() - self.shown_since
        return self.shown / dt if dt > 0 else 0.0

    # -- keys
    def key(self, e):
        k = (e.keysym or "").lower()
        if self.state.mark is not None:
            if k in [key for key, _n, _s in ve.LAYERS] or k == "u":
                layer = "unsure" if k == "u" else next(n for key, n, _s in ve.LAYERS if key == k)
                row = self.marks.mark(self.state.mark["t"], layer, self.loaded, self.geo,
                                      self.state.mark.get("point"), self.state.layers,
                                      (self.loaded.round or {}).get("round_no"))
                near = row["nearest"]
                self.state.message = (f"marked {layer} at {ve._hms(row['t_ms'])}: nearest "
                                      + (f"{near['stream']} {near['event_id']}" if near
                                         else row["nearest_reason"]))
                self.state.mark = None
                self.show()
            return
        if k in [key for key, _n, _s in ve.LAYERS]:
            name = next(n for key, n, _s in ve.LAYERS if key == k)
            self.state.layers ^= {name}
        elif k == "0":
            self.state.layers = {n for _k, n, _s in ve.LAYERS}
        elif k == "a":
            self.step(-1)
            return
        elif k == "d":
            self.step(1)
            return
        elif k == "m":
            self.pause()
            self.state.mark = {"t": self.frame_t, "point": None}
        elif k == "s":
            self.audio.enabled = not self.audio.enabled and self.audio.exe is not None
            self.state.audio = self.audio.status
            if self.state.playing:
                self.audio.play(self.frame_t) if self.audio.enabled else self.audio.stop()
        elif k == "h":
            self.state.help = not self.state.help
        elif k == "z":
            self.state.inset = not self.state.inset
        elif k == "p":
            p = self.screenshot()
            self.state.message = f"saved {p}"
        elif k == "q":
            self.quit()
            return
        self.show()

    def escape(self, _e):
        if self.state.mark is not None:
            self.state.mark = None
            self.state.message = "mark cancelled"
            self.show()
        else:
            self.quit()

    def click(self, e):
        x, y = e.x / self.scale, e.y / self.scale
        if y >= self.geo.height:
            self.seek(strip_time(self.loaded, self.geo.width, x))
        elif self.state.mark is not None:
            self.state.mark["point"] = (x, y)
            self.show()

    def retract(self, _e):
        row = self.marks.retract_last()
        self.state.message = ("retracted the last mark" if row else
                              "no mark of this run to retract")
        self.show()

    def screenshot(self) -> Path:
        self.shots.mkdir(parents=True, exist_ok=True)
        p = self.shots / f"{self.loaded.session_id}_{int(self.frame_t)}.png"
        cv2.imwrite(str(p), self.last_render)
        return p

    def quit(self):
        self.audio.stop()
        self.src.close()
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.audio.stop()


# -------------------------------------------------------------- the command

def window_summary(loaded: ve.Loaded) -> str:
    lines = [f"{loaded.session_id} window {ve._hms(loaded.t0)} .. {ve._hms(loaded.t1)}"]
    for key, layer, streams in ve.LAYERS:
        for s in streams:
            items = loaded.items.get(s, [])
            bad = sum(it.status in ve.NOT_READ for it in items)
            lines.append(f"  {key} {layer:13s} {s:21s} {len(items):6d} items  {bad:5d} "
                         f"amber  {loaded.presence.get(s)}  "
                         f"{loaded.versions.get(s) or ''}")
    return "\n".join(lines)


def shots(src, loaded, geo, times_ms, out: Path, layers=None) -> list[Path]:
    """Render frames at `times_ms` to PNGs without a window."""
    out.mkdir(parents=True, exist_ok=True)
    state = ViewState(backend=src.backend)
    if layers:
        state.layers = set(layers)
    paths = []
    for t in times_ms:
        f = src.seek(t)
        if f is None:
            continue
        ft = src.t_of(f)
        state.t_ms = ft
        img = render(src.bgr(f), ft, loaded, geo, state)
        p = out / f"{loaded.session_id}_R{(loaded.round or {}).get('round_no')}_{int(ft)}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    return paths


def main(args, store, manifest) -> int:
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    cv2.setNumThreads(1)
    if not args.normal_priority:
        lower_to_below_normal()
    sid = manifest["session_id"]
    if args.gaps:
        print(ve.format_gaps(ve.gap_rows(store, sid), sid))
        return 0
    if args.round is None:
        raise SystemExit("name a round: --round N (or --gaps)")
    r0, r1, row = ve.round_window(store, manifest, args.round)
    t0 = r0 + 1000.0 * (args.start or 0.0)
    t1 = min(r1, t0 + 1000.0 * args.seconds) if args.seconds else r1
    if t1 <= t0:
        raise SystemExit(f"empty window: round {args.round} is {ve._hms(r0)} .. {ve._hms(r1)}")
    loaded = ve.load(store, manifest, t0, t1, row)
    print(window_summary(loaded))
    if args.summary:
        return 0
    media = Path(manifest["source"]["path"])
    if not media.is_file():
        raise SystemExit(f"source media has moved: {media}")
    geo = Geometry.of(manifest)
    src = FrameSource(str(media), gpu=not args.cpu)
    print(f"decode     {src.backend}" + (f" (fallback: {src.fallback})"
                                        if getattr(src, "fallback", None) else ""))
    shot_dir = Path(args.shot_dir) if args.shot_dir else Path(store.root) / "overlays" / \
        "round_view"
    if args.shot:
        layers = None
        if args.layers:
            keys = set(args.layers.split(","))
            layers = {n for k, n, _s in ve.LAYERS if k in keys or n in keys}
        times = [t0 + 1000.0 * float(v) for v in args.shot.split(",")]
        for p in shots(src, loaded, geo, times, shot_dir, layers):
            print(f"wrote {p}")
        src.close()
        return 0
    labels = Path(args.labels) / f"{sid}.jsonl" if args.labels else ve.round_review_path(store, sid)
    marks = Marks(labels, sid)
    audio = Audio(str(media), enabled=not args.no_audio, volume=args.volume)
    print(f"audio      {audio.status}")
    print(f"marks      {labels} ({len(marks.live())} standing)")
    player = Player(src, loaded, geo, marks, audio, shot_dir, args.scale,
                    quit_after_s=args.quit_after, autoplay=args.autoplay)
    player.run()
    if args.quit_after and hasattr(player, "fps_at_quit"):
        print(f"shown      {player.fps_at_quit:.1f} frames/s of {src.fps:g}; audio process "
              f"{'running' if player.audio_ran else 'not running'} at the close")
    return 0
