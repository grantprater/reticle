"""Rerun one reader on part of a session and diff it against the stored streams.

A reader change is checked where it can matter, not over the whole capture:

* the frames are the stored HUD timeline's own timestamps, so every row the
  trial writes has a stored counterpart to compare with;
* `windows="occupied"` keeps only frames within `pad_ms` of a frame whose
  stored killfeed mask holds an entry; `"all"` keeps the whole timeline;
* `source="video"` seeks to each run of frames (`decode.seek_at`) instead of
  decoding from the file start; `source="cache"` reads the ROI crops
  (`roi_cache`) and decodes nothing.

The scoreboard reader's frames are its stored stream's samples instead, and
`"occupied"` keeps those inside the strip gate its crop cache is written
under (`roi_cache.scoreboard_gate`): an opportunity the stored strip
witness saw, not the reader's own opens.

The ally-icon reader's frames are its stored stream's frame rows, read at
the reader's declared rate, and `"occupied"` keeps those whose widget was
drawn. A
stream the cache fed (`frames_from`) holds only cached instants; one a
decode wrote at 2 Hz holds instants the 15 Hz cache mostly lacks, and the
trial refuses those as `not_cached` rather than reading a neighbour.

A frame the source does not yield is refused with the reason the cache
gives (`RoiCache.refusal`), never read as empty; the diff compares only the
frames read.

A trial writes nothing to the store. It is a test tier, not a scan: the
occupied windows come from stored output, so a change that finds entries
where the old reader saw none can only show up in a full scan, which stays
the acceptance run. Returns the rows and their diff.
"""
from __future__ import annotations

import json
import time

import numpy as np

def _killfeed_reader(ctx):
    from .killfeed import KillfeedPortraitReader
    return KillfeedPortraitReader(ctx.profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0, spans=None)


def _killfeed_rows(reader, sid: str) -> dict[str, list[dict]]:
    return {"killfeed_portrait": reader.events(sid), "killfeed_weapon": reader.weapon_events(sid),
            "killfeed_name": reader.name_events(sid)}


def _hud_reader(ctx):
    from types import SimpleNamespace
    from .hud_reader import HudReader
    # `scan`'s defaults: 2 Hz, and the glyph gates its parser sets.
    args = SimpleNamespace(hz=2.0, min_confidence=0.82, min_margin=0.05)
    return HudReader(ctx.store, ctx.manifest, ctx.profile, args)


def _hud_rows(reader, sid: str) -> dict[str, list[dict]]:
    return {"hud": reader.rows}


def _scoreboard_reader(ctx):
    from .scoreboard import ScoreboardReader
    # `scan`'s defaults: 2 Hz over the whole capture, the digit gates its
    # parser sets, and the agent art in the store.
    return ScoreboardReader(ctx.profile.name, hz=2.0, spans=None, min_confidence=0.82,
                            min_margin=0.05, icons_root=ctx.store.root)


def _scoreboard_rows(reader, sid: str) -> dict[str, list[dict]]:
    return {"scoreboard": reader.events(sid)}


def _ally_reader(ctx):
    from .minimap import ally_icon_reader
    # The declared rate (`ALLY_DESCRIPTOR_HZ`), never the stored stream's: a
    # stream at another rate shows as a moved `hz` field.
    return ally_icon_reader(ctx)


def _ally_rows(reader, sid: str) -> dict[str, list[dict]]:
    """The stream `scan` publishes, built in memory: the candidate revision's
    content address, the stored decision rule over its rows, and the replay."""
    from .adjudication.minimap_candidates import accepted, ally_decisions
    from .candidate_evidence import CANDIDATE_CONTRACT_VERSION, revision
    from .minimap import AllyIconReader
    # Through JSON, as `Store.write_candidates` stores them and `scan` reads them back.
    rows = json.loads(json.dumps(reader.candidate_rows(sid), allow_nan=False))
    frames = json.loads(json.dumps(reader.frames, allow_nan=False))
    rev = revision({"contract_version": CANDIDATE_CONTRACT_VERSION, "producer": "ally_icon",
                    "session_id": sid, "frames": frames, "rows": rows})
    kept = accepted(rows, ally_decisions(rows))
    return {"ally_icon": AllyIconReader.replay_events(
        sid, frames, kept, reader.hz, rev, frames_from=getattr(reader, "frames_from", "video"))}


def _ally_timeline(store, manifest: dict, windows: str, pad_ms: float):
    """`_hud_timeline` from the stored ally_icon frame rows; occupied keeps
    the frames whose widget the stored stream saw drawn, the opportunity to
    see an icon, not the icons it found."""
    sid = manifest["session_id"]
    frames = [r for r in store.read_events_kind("ally_icon", sid, "frame")
              if r.get("kind") == "frame"]
    if not frames:
        raise SystemExit(f"{sid}: no stored ally_icon frames -- run "
                         f"`reticle scan {sid} --only ally_icon`")
    if windows not in ("occupied", "all"):
        raise ValueError(f"unknown windows {windows!r}")
    want = [float(r["t_ms"]) for r in frames
            if windows == "all" or r.get("widget_drawn")]
    return len(frames), want, {r["t_ms"]: r["frame_idx"] for r in frames}


def _hud_timeline(store, manifest: dict, windows: str, pad_ms: float):
    """(timeline length, frames to read, frame index by time) from the stored
    HUD table."""
    hud = store.read_hud(manifest["session_id"], manifest["ingested_at"][:10]).to_pydict()
    return len(hud["t_ms"]), targets(hud, windows, pad_ms), dict(zip(hud["t_ms"], hud["frame_idx"]))


def _scoreboard_timeline(store, manifest: dict, windows: str, pad_ms: float):
    """`_hud_timeline` from the stored scoreboard stream's samples; occupied
    keeps those inside the strip gate (`scoreboard_targets`)."""
    sid = manifest["session_id"]
    samples = store.read_events_kind("scoreboard", sid, "sample")
    samples = [s for s in samples if s.get("kind") == "sample"]
    if not samples:
        raise SystemExit(f"{sid}: no stored scoreboard samples -- run "
                         f"`reticle scan {sid} --only scoreboard`")
    strip = store.read_events("scoreboard_strip", sid) if windows == "occupied" else None
    return (len(samples), scoreboard_targets(samples, strip, windows),
            {s["t_ms"]: s["frame_idx"] for s in samples})


def scoreboard_targets(samples: list[dict], strip_rows: list[dict] | None,
                       windows: str = "occupied") -> list[float]:
    """Times of the stored scoreboard samples the trial reads: all of them,
    or those inside the gate the scoreboard crop cache is written under."""
    from .roi_cache import in_spans, scoreboard_gate
    t = [float(s["t_ms"]) for s in samples]
    if windows == "all":
        return t
    if windows != "occupied":
        raise ValueError(f"unknown windows {windows!r}")
    gate, why = scoreboard_gate(strip_rows or [])
    if gate is None:
        raise SystemExit(f"no strip gate for the scoreboard trial: {why}")
    starts = [a for a, _ in gate["spans"]]
    return [x for x in t if in_spans(x, gate["spans"], starts)]


TRIAL_READERS = {
    # reader -> (the ROI cache set its reads stay inside, build, rows, streams, timeline)
    "killfeed": ("killfeed", _killfeed_reader, _killfeed_rows,
                 ("killfeed_portrait", "killfeed_weapon", "killfeed_name"), _hud_timeline),
    "hud": ("hud", _hud_reader, _hud_rows, ("hud",), _hud_timeline),
    "scoreboard": ("scoreboard", _scoreboard_reader, _scoreboard_rows, ("scoreboard",),
                   _scoreboard_timeline),
    # The minimap set's first rectangle only: the ability tray is not read.
    "ally_icon": ("minimap", _ally_reader, _ally_rows, ("ally_icon",), _ally_timeline),
}

#: Profile ROIs a trial decodes from its cache set, where fewer than the set's.
TRIAL_ROIS = {"ally_icon": ("minimap",)}


def targets(hud: dict, windows: str = "occupied", pad_ms: float = 2000.0) -> list[float]:
    """Timestamps of the stored HUD timeline the trial reads."""
    t = np.asarray(hud["t_ms"], dtype=float)
    if windows == "all":
        return t.tolist()
    if windows != "occupied":
        raise ValueError(f"unknown windows {windows!r}")
    occ = t[np.asarray([bool(m) for m in hud["kf_entry_mask"]])]
    if not len(occ):
        return []
    j = np.searchsorted(occ, t)
    near = np.minimum(np.abs(t - occ[np.clip(j, 0, len(occ) - 1)]),
                      np.abs(t - occ[np.clip(j - 1, 0, len(occ) - 1)]))
    return t[near <= pad_ms].tolist()


def _unstamped(row: dict) -> dict:
    """A row without its stream's version stamp, which a reader change moves
    on every row whether or not the reading moved."""
    return {k: v for k, v in row.items() if not k.endswith("_version")}


def _key(row: dict) -> str:
    return json.dumps(_unstamped(row), sort_keys=True)


def diff(new: list[dict], stored: list[dict], at: set[float]) -> dict:
    """Observation rows (coverage rows aside) compared at the trial's frames,
    version stamps aside. Rows that differ and share an `observation_key` are
    compared field by field in `fields`, so a change that moves one field
    says which."""
    obs = lambda rows: [r for r in rows if r.get("kind") not in ("coverage", "summary")
                        and "t_ms" in r]
    a = [_key(r) for r in obs(new)]
    b = [_key(r) for r in obs(stored) if float(r["t_ms"]) in at]
    sa, sb = set(a), set(b)
    outside = sum(float(r["t_ms"]) not in at for r in obs(stored))
    fields: dict[str, int] = {}
    by_key = {r["observation_key"]: _unstamped(r) for r in obs(stored)
              if "observation_key" in r and float(r["t_ms"]) in at}
    for r in obs(new):
        old = by_key.get(r.get("observation_key"))
        if old is None:
            continue
        r = _unstamped(r)
        for c in sorted(set(r) | set(old)):
            if r.get(c) != old.get(c):
                fields[c] = fields.get(c, 0) + 1
    return {"trial_rows": len(a), "stored_rows": len(b), "same": len(sa & sb),
            "only_trial": len(sa - sb), "only_stored": len(sb - sa),
            "stored_outside_frames": outside, "fields": dict(sorted(fields.items())),
            "example_only_trial": sorted(sa - sb)[:2], "example_only_stored": sorted(sb - sa)[:2]}


def diff_table(new: list[dict], stored: dict, at: set[float]) -> dict:
    """Reader rows against a stored table, column by column, at the trial's
    frames; the table's own stamp columns are not the reader's output."""
    by_t = {float(t): i for i, t in enumerate(stored["t_ms"])}
    norm = lambda v: list(v) if isinstance(v, tuple) else v
    same = moved = missing = 0
    cols: dict[str, int] = {}
    example = []
    for r in new:
        i = by_t.get(float(r["t_ms"]))
        if i is None:
            missing += 1
            continue
        bad = [c for c, v in r.items() if c in stored and norm(v) != norm(stored[c][i])]
        if bad:
            moved += 1
            for c in bad:
                cols[c] = cols.get(c, 0) + 1
            if len(example) < 2:
                example.append(json.dumps({c: [r[c], stored[c][i]] for c in bad[:3]},
                                          default=str))
        else:
            same += 1
    return {"trial_rows": len(new), "stored_rows": len(at & set(by_t)), "same": same,
            "only_trial": moved + missing, "only_stored": moved, "stored_outside_frames": 0,
            "columns": cols, "example_only_trial": example, "example_only_stored": []}


def run(store, manifest: dict, reader: str = "killfeed", source: str = "video",
        windows: str = "occupied", pad_ms: float = 2000.0,
        between: tuple[float, float] | None = None) -> dict:
    """`between` (t0_ms, t1_ms), inclusive, bounds the trial to one slice of
    the timeline, such as a round; the diff compares only frames inside it."""
    from .decode import seek_at
    from .passes import SessionContext
    from .profiles import get_profile
    from .roi_cache import RoiCache

    if reader not in TRIAL_READERS:
        raise ValueError(f"no trial for reader {reader!r}; have {sorted(TRIAL_READERS)}")
    roi_name, build, output, streams, timeline = TRIAL_READERS[reader]
    sid = manifest["session_id"]
    profile = get_profile(manifest["source_profile"])
    ctx = SessionContext(store=store, manifest=manifest, profile=profile)
    n_timeline, want, stored_idx = timeline(store, manifest, windows, pad_ms)
    if between is not None:
        want = [t for t in want if between[0] <= t <= between[1]]
    r = build(ctx)
    t0 = time.perf_counter()
    cache = None
    if source == "video":
        frames = seek_at(str(ctx.media), want, ctx.fps)
    elif source == "cache":
        cache, why = RoiCache.load(store.root, manifest, profile, roi_name)
        if cache is None:
            raise SystemExit(f"{sid}: no usable {roi_name} ROI cache ({why}) -- run "
                             f"`reticle scan {sid} --only roi_cache --cache-roi {roi_name}`")
        frames = cache.samples(want, rois=TRIAL_ROIS.get(reader, roi_name))
    else:
        raise ValueError(f"unknown source {source!r}")
    read: list[float] = []
    moved_idx = 0
    for smp in frames:
        idx = int(stored_idx.get(smp.t_ms, smp.frame_idx))
        moved_idx += idx != int(smp.frame_idx)
        smp.frame_idx = idx
        r.feed(smp)
        read.append(float(smp.t_ms))
    seconds = time.perf_counter() - t0
    # A frame the source did not yield is refused, with the cache's reason.
    got = set(read)
    refused: dict[str, int] = {}
    for t in want:
        if float(t) not in got:
            why = cache.refusal(t) if cache is not None else "not_decoded"
            refused[why] = refused.get(why, 0) + 1
    # The store writes plain JSON; compare what it would have written.
    rows = {s: [json.loads(json.dumps(x, separators=(",", ":"), allow_nan=False))
                for x in rs] for s, rs in output(r, sid).items()}
    at = got
    if "hud" in streams:
        hud = store.read_hud(sid, manifest["ingested_at"][:10]).to_pydict()
    diffs = {s: (diff_table(rows[s], hud, at) if s == "hud"
                 else diff(rows[s], store.read_events(s, sid), at)) for s in streams}
    out = {"session_id": sid, "reader": reader, "source": source, "windows": windows,
           "pad_ms": pad_ms, "between": between, "timeline": n_timeline, "frames": len(read),
           "asked": len(want), "refused": dict(sorted(refused.items())),
           "frame_idx_moved": moved_idx, "seconds": round(seconds, 1), "diff": diffs,
           "rows": rows}
    if reader == "scoreboard":
        # The GPU and CPU scorers differ in the fourth decimal; a trial on the
        # other one moves portrait scores without any reader change.
        from .scoreboard import portrait_scorer
        stored = store.read_events_kind("scoreboard", sid, "coverage")
        out["portrait_scorer"] = {"stored": stored[0].get("portrait_scorer") if stored else None,
                                  "trial": portrait_scorer()}
    return out
