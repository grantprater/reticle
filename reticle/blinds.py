"""Blind spans: where a flash washes the HUD out, from stored primitives.

Skye's Guiding Light and Phoenix's Curveball, when they blind the player,
paint the whole screen in a uniform wash that hides the killfeed
[domain:abilities/skye-guiding-light-blind-screen]
[domain:abilities/phoenix-curveball-blind-screen]. An entry the wash hides is
hidden, not expired. At a06f04a0059f (`C:/Users/grant/Videos/2026-08-26
09-56-37.mp4`) Riot's kill of Deadlock at 1768.2 s draws an entry read once,
at 1768.0 s (slot 1, divider 186, ally victim); the wash hides it from
1768.4 s, and the first frame after it, 1771.0 s, reads the entry faded, its
plates one colour and its victim side enemy. The killfeed tracker dropped the
one-sample onset and began a new entry there, on the wrong side.

Why this is a recomputed rule and not a reader
----------------------------------------------
Like a capture stall (`stalls`), a blind is a property of the frame, and the
shared decode pass already stores what shows it: `l1/primitives` holds, per
frame at 5 Hz, the killfeed ROI's edge density (`killfeed_edge`) and the
minimap ROI's luma spread (`minimap_std`). A wash leaves the killfeed ROI with
no edge at all and flattens the minimap, which in live play always carries
its walls and icons. Over the 20 Riot-scored matches that store both columns
(187,701 live samples, motion above zero and mean luma at least 0.25), the
minimap's spread falls to 0.06 or below on 0.8% and does so with an edgeless
killfeed on 0.25%; its median is 0.157.

The rule
--------
A **core** is a run of at least `MIN_SAMPLES` consecutive samples whose
killfeed ROI has no edge (`killfeed_edge <= EDGE_EPS`), whose median minimap
spread is at most `MINIMAP_STD_MAX` and whose median mean luma is at least
`LUMA_MIN` (a dark frame is a loading or black screen, not a wash) with the
source moving (median motion above zero; a frozen frame is a stall). An
edgeless killfeed alone is no blind: an empty killfeed over plain scenery
reads no edge on 7.7% of live samples.

After the core the wash flares and fades: at a06f04a0059f the frame's mean
luma runs 0.42 in the core, 0.70 at 1770.6 s, then 0.61, 0.52, 0.44 and 0.36
at 1771.4 s; c62c2b06bcfb 761.0 s and bfad2778a372 1961.2 s fade alike in 0.6
to 0.8 s. A span therefore runs on past its core over every following sample
whose mean luma exceeds the core's median, for at most `TAIL_MS`. A frame in
that tail shows the killfeed faded under the wash: its entries are there,
their plate colours are not.

What the spans are for: a consumer joins them and decides for itself. The
killfeed tracker (`checks.track_entries`) ages a track without counting the
hidden time, and reads no victim side in a washed frame. Over the corpus
survey (`reticle.blinds.spans` on 21 matches) every stored HUD killfeed read
inside a span fell in its tail, none in a core.

What this does not know: which ability blinded the player, whether a blind
the wash does not cover (Reyna's Leer darkens only the minimap
[domain:abilities/reyna-leer-darkens-minimap]) hides the killfeed, and
whether every blind's wash flattens the minimap as these do.

Owns [owns:blind-screen].
"""
from __future__ import annotations

import numpy as np

BLIND_VERSION = "blinds-0.1.0"

#: The killfeed ROI's edge density at or below which it shows no edge.
EDGE_EPS = 0.001
#: A core's median minimap luma spread at or below which the minimap is washed.
MINIMAP_STD_MAX = 0.06
#: A core's median mean luma below which the frame is dark, not washed.
LUMA_MIN = 0.25
#: The fewest consecutive primitive samples (5 Hz) a core holds.
MIN_SAMPLES = 2
#: The longest the fading wash runs past its core.
TAIL_MS = 1000.0


def spans(prim: dict) -> list[dict]:
    """Blind spans over one session's primitives (`Store.read_primitives`);
    `{"t_start_ms", "t_end_ms", "core_end_ms", "core_luma"}` per span, in
    time order, both ends closed. Pure, no I/O. A table without the
    `killfeed_edge` column yields []."""
    if "killfeed_edge" not in prim or "minimap_std" not in prim:
        return []
    t = np.asarray(prim["t_ms"], dtype=float)
    order = np.argsort(t, kind="stable")
    t = t[order]
    col = lambda k: np.asarray(prim[k], dtype=float)[order]
    edge, mm, luma, motion = col("killfeed_edge"), col("minimap_std"), col("luma_mean"), col("motion")
    hid = (edge <= EDGE_EPS).astype(np.int8)
    d = np.diff(np.concatenate(([0], hid, [0])))
    out = []
    for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if b - a < MIN_SAMPLES:
            continue
        if not (np.median(mm[a:b]) <= MINIMAP_STD_MAX and np.median(luma[a:b]) >= LUMA_MIN
                and np.median(motion[a:b]) > 0):
            continue
        core = float(np.median(luma[a:b]))
        after = np.flatnonzero((t > t[b - 1]) & (t <= t[b - 1] + TAIL_MS))
        bright = luma[after] > core
        # The tail runs while the wash stays brighter than the core.
        n = int(np.argmin(bright)) if not bright.all() else bright.size
        z = after[n - 1] if n else b - 1
        out.append({"t_start_ms": float(t[a]), "t_end_ms": float(t[z]),
                    "core_end_ms": float(t[b - 1]), "core_luma": round(core, 4)})
    merged: list[dict] = []
    for s in out:
        if merged and s["t_start_ms"] <= merged[-1]["t_end_ms"]:
            merged[-1]["t_end_ms"] = max(merged[-1]["t_end_ms"], s["t_end_ms"])
            merged[-1]["core_end_ms"] = max(merged[-1]["core_end_ms"], s["core_end_ms"])
        else:
            merged.append(s)
    return merged


def for_session(store, session_id: str, date: str) -> list[dict] | None:
    """The session's blind spans, or None when it has no primitives table or
    the table predates the `killfeed_edge` column: None is unknown, not no
    blind."""
    if not store.has_primitives(session_id, date):
        return None
    prim = store.read_primitives(session_id, date)
    if "killfeed_edge" not in prim or "minimap_std" not in prim:
        return None
    return spans(prim)


def inside(span_list, times) -> np.ndarray:
    """Per time in `times`, whether a span covers it (both ends closed)."""
    t = np.asarray(list(times), dtype=float)
    out = np.zeros(t.size, dtype=bool)
    for s in span_list or ():
        out |= (t >= s["t_start_ms"]) & (t <= s["t_end_ms"])
    return out


def hidden_ms(span_list, t0: float, t1: float) -> float:
    """How long the spans cover between `t0` and `t1`: time the killfeed was
    not seen."""
    return float(sum(max(0.0, min(t1, s["t_end_ms"]) - max(t0, s["t_start_ms"]))
                     for s in span_list or ()))
