r"""The self icon's portrait scored against the agents' art: the player's second witness.

    .\.venv\Scripts\python.exe -m reticle self-icon <session> | --all

Owns [owns:self-icon-portrait].

The player's own minimap icon is the agent's portrait inside a yellow ring
(`prototypes/self_agent.py` inspected it). `Lineup.add_self` was written to
take its composition and nothing called it, so every stored lineup held no
self-icon frame and the tray was the player's only witness. This module reads
the portrait from the stored minimap crops, decodes no video, and stores each
frame's scores against every agent's art. `lineup.load_lineup` reads the
stored rows as the lineup's `self_icon` witness, and the identity arbiter
ranks it among the ally five (`identity._self_icon_claim`), so no lineup
rewrite is needed.

**Two descriptors, and the claim reads the calibrated one.** Each scored frame
stores what `Lineup.add_self` accumulates, the composition against the
official art (`lineup.gallery_scores`, `composition_scores`), and the minimap
portrait's feature families (`ally_portrait.portrait_features`) with their
log likelihood under each agent's rendered-art reference
(`identity.rendered_art_scores`, `art_scores`), the scorer the teammate
channel prefers. The witness's `scores` are the mean `art_scores`, gated at
the reference table's `margin_min`, wherever every scored frame has them, and
the mean composition at `identity.SIDE_MARGIN_MIN` otherwise; the two are
never mixed. On all 21 lineup sessions the composition ranked Chamber first of
29 on every capture where the tray names Skye, and named Chamber where the
ally side holds one; the crops show Skye's portrait (docs/SELF_ICON_WITNESS.md).

**Only frames where the player lives.** After the player dies the view goes
to a teammate [domain:hud/tray-after-player-death], and the tray's votes pool
those frames. This reader takes a frame only where the stored roster reads all
five allies alive (`roster.alive_counts`, owner `alive-count`) at both roster
samples around it: five living allies include the player, so the view is the
player's. The gate rests on neither the tray nor the killfeed, so the tray's
claim and this one stay independent witnesses.

**What each grid frame records.** A frame is scored, or refused with the
first reason that applies: `not_all_alive` (the gate), `widget_not_drawn`
(`minimap.widget_drawn` over the baked geometry), `no_self_fit`
(`minimap.self_icons` fits no ring), `on_spike_glyph` (every fit lands on
the spike glyph, `spike.on_glyph`; a fit that does is skipped for the next
by coverage), `ally_overlap` (a teammate's icon disc
touches the self icon's, so its portrait is drawn over the player's),
`interior_too_thin` (fewer than MIN_PIXELS portrait pixels,
`minimap.self_portrait_pixels`). Refusals stay stored, so coverage is read
from the rows and not assumed.

**The portrait sits at the teardrop's centre.** The ring fit finds the icon
(`cx`, `cy`) and its centre sits a few pixels toward the icon's lobe. The
portrait is cut, aligned and tested for overlap at the self teardrop's centre
(`x`, `y`, `teardrop.SelfConeReader`) where the shape reads on a 465 px
widget, and at the ring fit's otherwise; `origin` names which and
`origin_reason` says why (`unlabelled_scale` on a smaller widget, where the
teardrop's centre fit the portrait no better). Aligned at the teardrop's
centre the stored self frames fit their ally five more tightly
(docs/STATISTICAL_ADJUDICATOR.md, E6, rule B').

This describes; `adjudication.identity` names.
"""
from __future__ import annotations

import numpy as np

from .version import (ALLY_PORTRAIT_FEATURES_VERSION, SELF_ICON_VERSION, SPIKE_VERSION,
                      TEARDROP_VERSION)

#: Fewer portrait pixels than this and the histogram is noise.
MIN_PIXELS = 12
#: The grid step inside each cached round span, in seconds.
STEP_S = 1.0
#: How far, in ms, a roster sample may lie from the frame it gates.
ROSTER_GAP_MS = 1000.0

REFUSALS = ("not_all_alive", "widget_not_drawn", "no_self_fit", "on_spike_glyph",
            "ally_overlap", "interior_too_thin")


def all_alive(roster_t, roster_alive, t_ms: float, n: int = 5) -> bool:
    """True where the roster samples on both sides of `t_ms` read `n` allies
    alive, each within ROSTER_GAP_MS."""
    rt = np.asarray(roster_t, float)
    if not len(rt):
        return False
    i = int(np.searchsorted(rt, t_ms))
    lo, hi = max(0, i - 1), min(len(rt) - 1, i)
    return all(abs(rt[k] - t_ms) <= ROSTER_GAP_MS and roster_alive[k] == n for k in (lo, hi))


def read_frame(crop: np.ndarray, ctx: dict, gal: dict, references: dict | None = None) -> dict:
    """One frame's self-icon reading: the fit and the scores, or a refusal.

    `ctx` holds the baked geometry's `floor`, `slab`, `static` and `sgray`;
    `gal` is `lineup.load_gallery`'s and `references` the rendered-art table
    (`identity.load_ally_portrait_references`), or None."""
    from . import ally_portrait
    from .adjudication.identity import rendered_art_scores
    from .lineup import _composition, gallery_scores
    from . import spike
    from .minimap import (ally_icons, portrait_key, self_icons, self_portrait_pixels,
                          widget_drawn, widget_scale)
    from .teardrop import SelfConeReader, posed, self_portrait_pose

    if not widget_drawn(crop, ctx["sgray"], ctx["floor"]):
        return {"reason": "widget_not_drawn"}
    fits = self_icons(crop, ctx["floor"], require_facing=False, support=ctx["slab"])
    if not fits:
        return {"reason": "no_self_fit"}
    allies = ally_icons(crop, ctx["floor"], support=ctx["slab"], static=ctx["static"])
    glyphs = spike.accepted(spike.glyph_fits(crop, ctx["slab"]))
    sc = widget_scale(crop.shape[1])
    clear = [d for d in fits
             if spike.on_glyph(d["cx"], d["cy"], glyphs, sc, fits + allies) is None]
    if not clear:
        g = spike.on_glyph(fits[0]["cx"], fits[0]["cy"], glyphs, sc, fits + allies)
        return {"cx": round(fits[0]["cx"], 2), "cy": round(fits[0]["cy"], 2),
                "spike_glyph": {k: g[k] for k in ("cx", "cy", "state")},
                "reason": "on_spike_glyph"}
    ring = max(clear, key=lambda d: d["cov"])
    # The ring fit finds the icon; the portrait is cut, aligned and tested for
    # overlap at the teardrop's centre where it reads (0.5.0).
    pose = self_portrait_pose(SelfConeReader(sc).read(crop, ring["cx"], ring["cy"]), sc,
                              ring["cx"], ring["cy"])
    f = posed(ring, pose)
    row = {"cx": round(ring["cx"], 2), "cy": round(ring["cy"], 2), "r": int(f["r"]),
           "cov": round(f["cov"], 3), "x": round(f["cx"], 2), "y": round(f["cy"], 2),
           "origin": pose["origin"], "origin_reason": pose.get("reason")}
    near = min((float(np.hypot(a["cx"] - f["cx"], a["cy"] - f["cy"])) - a["r"] - f["r"]
                for a in allies), default=None)
    row["ally_gap_px"] = None if near is None else round(near, 1)
    if near is not None and near < 0:
        return {**row, "reason": "ally_overlap"}
    win, keep = self_portrait_pixels(crop, f, allies)
    row["pixels"] = int(keep.sum())
    if row["pixels"] < MIN_PIXELS:
        return {**row, "reason": "interior_too_thin"}
    hq = _composition(crop[win], keep)
    row["composition_scores"] = {n: round(v, 5)
                                 for n, v in sorted(gallery_scores(hq, gal).items())}
    img = ally_portrait.align_icon(crop, f["cx"], f["cy"])
    feats = ally_portrait.portrait_features(img, portrait_key(img))
    row["portrait_features"] = ally_portrait.stored(feats)
    art = (rendered_art_scores(feats, sorted(references["agents"]), references)
           if references else None)
    row["art_scores"] = None if art is None else {n: round(v, 5) for n, v in art.items()}
    return {**row, "reason": None}


def _mean(dicts: list[dict]) -> dict:
    return {n: round(float(np.mean([d[n] for d in dicts])), 5) for n in sorted(dicts[0])}


def icon_witness(frames: list[dict], references: dict | None = None) -> dict:
    """The lineup's `self_icon` witness from frame rows: the frame count, the
    mean score per agent and the margin its claim is gated at.

    The mean `art_scores` at the reference table's `margin_min` where every
    scored frame has them (`reference_source` "rendered_art"), else the mean
    `composition_scores` with no `margin_min` of its own ("official_art", as
    `Lineup.player_witnesses` reports `Lineup.add_self`'s). The composition's
    mean is kept beside the art's. With no scored frame, `reason` names the
    commonest refusal past the gate."""
    scored = [r for r in frames if r.get("reason") is None and r.get("composition_scores")]
    out = {"frames": len(scored), "scores": {}, "self_icon_version": SELF_ICON_VERSION}
    if scored:
        comp = _mean([r["composition_scores"] for r in scored])
        if references and all(r.get("art_scores") for r in scored):
            out.update(scores=_mean([r["art_scores"] for r in scored]),
                       reference_source="rendered_art",
                       margin_min=references["margin_min"],
                       reference_version=references.get("version"),
                       composition_scores=comp)
        else:
            out.update(scores=comp, reference_source="official_art")
    else:
        # The gate refuses by design; name what refused the frames it passed.
        why = [r["reason"] for r in frames if r.get("reason")]
        read = [w for w in why if w != "not_all_alive"] or why
        out["reason"] = (max(sorted(set(read)), key=read.count) if read else "no_grid_frames")
    return out


def stored_witness(rows: list[dict]) -> dict | None:
    """The `self_icon` witness stored by `reticle self-icon`, or None where
    the session has no current rows."""
    if not rows or rows[0].get("self_icon_version") != SELF_ICON_VERSION:
        return None
    return rows[0].get("witness")


def read_session(store, sid: str, gal: dict, references: dict | None = None,
                 step_s: float = STEP_S) -> dict | None:
    """Every grid frame of the session's minimap crop cache, read.

    Returns `{"rows": [...]}`, a coverage row first and a row per grid frame,
    or `{"skipped": why}`."""
    import glob

    import cv2
    import pyarrow.parquet as pq

    from . import geometry
    from .minimap import floor_mask, slab_mask
    from .profiles import get_profile
    from .roi_cache import RoiCache

    man = store.read_manifest(sid)
    cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "minimap")
    if cache is None or not cache.record.get("spans"):
        return {"skipped": f"no minimap crop cache with round spans ({why})"}
    path = store.roster_path(sid, man["ingested_at"][:10])
    if not path.is_file():
        found = glob.glob(str(store.root / "l1" / "roster" / "*" / f"session={sid}" / "*.parquet"))
        path = found[-1] if found else None
    if path is None:
        return {"skipped": "no stored roster"}
    table = pq.read_table(path, columns=["t_ms", "alive_ally", "roster_version"])
    rt = table.column("t_ms").to_numpy()
    ra = [(-1 if a is None else int(a)) for a in table.column("alive_ally").to_pylist()]
    roster_version = (table.column("roster_version")[0].as_py() if table.num_rows else None)
    med = geometry.reference_static(sid, store.root)
    sd = geometry.stability(sid, store.root, med.shape[:2])
    ctx = {"floor": floor_mask(med, sd=sd), "slab": slab_mask(med, sd=sd), "static": med,
           "sgray": cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)}
    x0, y0, x1, y1 = cache.rect_of("minimap")
    t = np.unique(np.asarray(cache.t_ms, float))
    frames = []
    for si, (a, b) in enumerate(cache.record["spans"]):
        ts = t[(t >= a) & (t <= b)]
        if not len(ts):
            continue
        want = np.arange(ts[0], ts[-1] + 1, step_s * 1000.0)
        grid = [float(x) for x in ts[np.unique(np.searchsorted(ts, want).clip(0, len(ts) - 1))]]
        alive = [g for g in grid if all_alive(rt, ra, g)]
        frames += [{"kind": "frame", "t_ms": g, "cache_span": si, "reason": "not_all_alive"}
                   for g in grid if g not in set(alive)]
        for smp in cache.samples(alive, rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            if crop.shape[:2] != ctx["floor"].shape:
                frames.append({"kind": "frame", "t_ms": float(smp.t_ms), "cache_span": si,
                               "reason": "widget_not_drawn"})
                continue
            frames.append({"kind": "frame", "t_ms": float(smp.t_ms), "cache_span": si,
                           **read_frame(crop, ctx, gal, references)})
    frames.sort(key=lambda r: r["t_ms"])
    counts = {k: sum(r["reason"] == k for r in frames) for k in REFUSALS}
    head = {"kind": "coverage", "session": sid, "self_icon_version": SELF_ICON_VERSION,
            "roi_cache_version": cache.record.get("version"), "roster_version": roster_version,
            "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "spike_version": SPIKE_VERSION, "teardrop_version": TEARDROP_VERSION,
            "reference_version": (references or {}).get("version"),
            "parameters": {"step_s": step_s, "MIN_PIXELS": MIN_PIXELS,
                           "ROSTER_GAP_MS": ROSTER_GAP_MS},
            "grid_frames": len(frames), "scored": sum(r["reason"] is None for r in frames),
            "refused": counts, "witness": icon_witness(frames, references)}
    for r in frames:
        r["self_icon_version"] = SELF_ICON_VERSION
    return {"rows": [head] + frames}
