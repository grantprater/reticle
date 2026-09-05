"""Find every distinct thing that appears on the minimap in a short, controlled ability-demo clip.

    .\\.venv\\Scripts\\python.exe prototypes\\scan_ability_clip.py <session> [--step-ms 150]

Then review and name what it found:

    .\\.venv\\Scripts\\python.exe prototypes\\label_ability.py <session>

Why this is a different tool from label_dynamic.py's detection stage
----------------------------------------------------------------------
`label_dynamic.py` samples SPARSELY across a whole match -- a handful of times
per round, stratified over rounds and trimmed to live play -- because a match
is long and the point is to characterise a RATE without spending the time
on every frame. A demo clip the player records deliberately (one agent, every
ability, on purpose) is the opposite problem: short, near-empty by design, and
the entire point is to catch EVERY placement -- missing one defeats the
exercise. `reticle.rounds.round_bounds` also has nothing to trim to: a clip
with no scoreline has no rounds and no buy phase. So this scans DENSELY, every
`step_ms`, across the WHOLE clip instead, with no notion of match structure at
all.

This produces CANDIDATES, not verified labels, and the file it writes says so.
Every row is `by: "claude", kind: "ability"` -- a guess, not an answer. It
writes to `<store>/labels/ability_candidates/`, never to
`<store>/labels/minimap_dynamic/` -- writing into the human classify-pass
store would make `label_dynamic.py` silently skip these positions as already
done the next time it ran on this session, which is exactly the seeding
mistake `label_icon_agent.py`'s docstring warns against ("provenance decides,
not presence"). `by` says who wrote a row; here it says "not a person yet".

The guess is only ever `ability` because that is what the clip is FOR --
almost everything a dense scan finds on an ability-demo minimap is the
ability itself, or is the player icon sitting there the whole time.
No attempt is made here to tell those apart algorithmically: `label_ability.py`
already has the correction path for it (`0 = not actually an ability`), and
sorting the two apart by eye costs the player nothing on a clip this short. That
split -- I propose positions, the player confirms/rejects and names -- is exactly
what he asked for.

Tracking, not per-frame sampling
----------------------------------
A raw per-frame scan produces one row per frame an object is visible, which is
the same over-counting `label_dynamic.py`'s `diversify()` exists to fix -- an
ability sitting on screen for 8 seconds at 150ms steps is ~53 near-duplicate
detections of ONE thing. This clusters consecutive detections into TRACKS
instead: a detection within `TRACK_PX` of an open track's last position
extends it; a track with no matching detection for more than `TRACK_GAP_MS`
closes (one missed frame should not end a track -- the icon did not vanish,
the detector just missed a frame, the same reasoning `KF_MIN_OBS` and thin-track
handling use elsewhere in this project). Each finished track becomes ONE
candidate row, timestamped at its FIRST observation, carrying `n_observations`
(frames it was seen) and `duration_ms` so a one-frame flicker
(`--persist-min`) can be told from something that was actually placed.

Two re-checks from `ability_shape.py`, added after the FIRST real run of this
tool (`eb10db50b1fb`) came back 19 of 20 candidates `not_ability`
------------------------------------------------------------------------------
Both are computed once per track, on the raw frame at its onset, rather than
from `d`'s own diff-blob -- see that module's docstring for why the blob
shape is the wrong thing to measure (it merges with adjacent geometry, and it
can barely register a long-placed device that baked into its own static
reference).

* **`device_glyph` (`cov`, `inner_edge`, `r`)** -- is there a real hard-edged
  ring here. Reported, not filtered by default: it is scoped to small
  device-glyph icons (Cypher, Deadlock) and scores real Brimstone-style
  translucent overlays low on purpose, since those have no hard boundary at
  any radius. `--device-inner-min` opts into dropping candidates below a
  threshold, and it must not be turned on for a clip that can contain an
  area/ultimate ability;
* **`colour_local` / `colour_frac_local`** -- `blob_colour` re-scored on a
  fixed disc at the candidate point instead of the production blob's own
  (possibly geometry-merged) mask, which can dilute a genuinely coloured
  object's fraction under threshold. Reported alongside the original
  `colour`/`colour_frac` rather than replacing them, since `--colour`
  filtering above already ran against the original by the time this is
  computed -- a divergence between the two fields is itself worth a look.

**`host_span` (`dynamic_eval.py`'s pre-top-hat raw-diff-region size, shipped
at 77%/96% on `a06f04a0059f`) was tried here too and FAILED to transfer** --
tested against the real `eb10db50b1fb` labels (5 confirmed
`Cypher:Trapwire`, 45 confirmed `not_ability`) before wiring it in: 11.1%
precision at the same threshold, barely above the 10.2% base rate. Do not
re-try it blind here; whatever separates real from junk on the Sonic Sensor
class does not hold for the trapwire.

**`self_icon_dist` -- the fix that actually worked, and why it's a different
KIND of check from the two above.** Line 33 above named this gap when the
tool was built ("the player icon sitting there the whole time... No
attempt is made here to tell those apart algorithmically") and it sat
unaddressed until the player, reading a rendered comparison of real vs false
candidates, named the pattern by eye: several false positives had no
trapwire in the crop AT ALL, just his own icon. `device_glyph`/`host_span`
are GENERIC shape/size guesses that turned out not to transfer between
object classes; this instead reuses `reticle.minimap.self_rings` --
already-shipped, already-validated code for a DIFFERENT job (self-position
tracking) -- to ask a specific, answerable question: is the local player's
own icon sitting right here. Distance from the candidate to the nearest
fitted self-ring, on the SAME real labels: real trapwire 8.0-31.5px, false
positives 2.6-6.5px (n=5 of 6 -- clean separation at `SELF_ICON_DIST_MIN=7`).
**What it does NOT fix**: the sixth false positive, a circle sitting on the
barrier/wire's own rendering below the real icon, scored 45.4px -- far from
the self icon, for an entirely unrelated reason. That is still open. Do not
read this check's success as evidence the OTHER problem is close to solved.

**SAMPLED OVER THE WHOLE TRACK from 2026-09-04, not once at its birth. Phase 0
of the temporal design doc** (`docs/ability-temporal.html`), and it is a
COVERAGE repair, not a new idea. `self_icon_dist` was computed on the single
frame that opened a track, so one bad frame nulled the whole candidate --
`null` on 25 of Astra's 43 rows and 58% corpus-wide. That is not a detection
failure: `self_rings` finds the player in 70-100% of frames and the floor gate
costs 1.7% at worst. The nulls are CORRELATED. A candidate is
disproportionately born in the frame where something covers the widget, which
is exactly when the self colour is hidden, so the one sample lands at the worst
possible moment available. the reading of the ranked gallery -- *all the
weakest examples are literally only player icons or very close to player
icons* -- confirms this is the one filter here that works, so its coverage was
the highest-value repair on the board.

`mm.self_rings` is now called once per FRAME rather than once per new track
(every track matching a detection in that frame wants the same fit), and each
track keeps the series of distances from its OWN current position to the
nearest ring. Measuring from the current position rather than the birth
position is the point: a candidate that IS the player's icon stays glued to it
as he moves, while a real placed device falls behind him.

**`self_icon_dist` is the MEDIAN over the track, not the min, and that
overturns what NOTES proposed.** NOTES said take the min; measured against
the real `eb10db50b1fb` labels at the SAME already-set threshold
(`SELF_ICON_DIST_MIN = 7` -- nothing was re-fitted, this is a comparison of two
aggregates at one fixed gate):

    aggregate   real trapwires kept   not_ability dropped
    min                 3 of 5             10 of 26  (38%)
    median              5 of 5              8 of 26  (31%)

Min drops two real trapwires that score 4.54 and 4.04 px, for seven percentage
points more junk. That is a bad trade in the direction that matters, since
recall is the scarce quantity here.

**The mechanism, and why min looked right until it was measured.** Min was
proposed as part of a COVERAGE fix, and the coverage fix is the per-frame
sampling -- not the aggregate. Once a whole track is sampled, min stops meaning
"is the player's icon here" and starts meaning "was the player EVER here", which
is a different and much more common event. It is visible directly in the Astra
clip: candidates scoring min 2.7 / median 54.6 over 275 ring fits, and min 0.26
/ median 20.4 over 211. Those are objects the player walked over once. The genuine
player-icon fragments score small on BOTH (2.3/2.3, 0.34/2.43, 2.18/2.18), so
the median separates the two and the min collapses them.

`self_icon_dist_min` and `self_icon_n` (frames that produced a ring at all) are
stored alongside, the same way `label_dynamic` stores colour, area, box and
aspect on purpose -- so this comparison can be re-run as the label set grows
rather than re-argued. **Caveat on the table above, and it is the standing
one**: n=5 real of ONE ability class on ONE session. It is a like-for-like
comparison against the population the 7px threshold was itself set on, which
makes it fair, not general.

**Known and NOT fixed here**: `ability_corpus.load_events` takes `min(dists)`
across the fragments of a grouped event, which re-introduces exactly this
failure one level up -- an event with one near-player fragment inherits its
distance. Same argument, same fix, different module; recorded in NOTES.

**`geo_label` -- what `minimap_geometry` classification says is under the
candidate, found checking the hunch that "quite a few" candidates on
`79a706a7ce4c` (the bigmap Cypher session) were off the map entirely.**
Two real, different things turned up:

* **3 candidates sit on VOID outright** -- `searchable()` is supposed to make
  this impossible, so this is a genuine (small, low-`n_observations`) leak,
  most likely `floor_mask`'s own dilation margin admitting a thin
  void-adjacent strip. Not fixed here; recorded so it isn't mistaken for
  something else next time it's seen.
* **PLANT (bomb site) is a strong prior for junk, NOT a safe exclusion.**
  15 of 68 candidates here sit on a plant zone and the player called every one of
  them `not_ability` -- but checked against every session with confirmed real
  labels, 1 of 53 real abilities on `a06f04a0059f` and 1 of 35 on
  `5822b6646448` DO sit on a plant zone. Excluding it outright would be the
  exact population-mismatch mistake this project has made before (*0 of 254
  hand-marked icons sit on a HOLE* nearly cut holes wholesale) in a new
  costume, so `geo_label` is reported, not filtered.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
from reticle import minimap as mm                                 # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_temporal import usable, drawn                        # noqa: E402
import ability_shape as ashape                                    # noqa: E402

#: Below this, a candidate is almost certainly the local player's OWN icon,
#: not a placed device -- see ability_shape.py / scan() for how this was
#: found and what it does and does not fix.
SELF_ICON_DIST_MIN = 7.0

#: minimap_geometry.py's label enum, by value -- NOT re-imported, because that
#: module also exports unrelated same-valued constants (LINE_CLOSE=5 collided
#: with PLANT=5 once already, 2026-09-02). Kept in sync by hand; it is a
#: closed set that has not changed since the module was written.
GEO_LABEL_NAMES = {0: "VOID", 1: "FLOOR", 2: "HOLE", 3: "BORDER", 4: "BOXEDGE", 5: "PLANT"}

STORE = Path.home() / "reticle-store"

#: Same radius `label_dynamic.py`'s onset check uses for "is this the same object".
TRACK_PX = 10
#: Bridge this much missed detection before closing a track. Generous relative
#: to `step_ms` so one or two dropped frames (occlusion, a brief unreadable
#: frame) do not fracture one placement into several candidates.
TRACK_GAP_MS = 600


def _self_dist(rings, x, y):
    """Distance from (x, y) to the nearest fitted self-ring, or None if none fit.

    None means `self_rings` did not find the player in that frame -- absence of
    evidence, not evidence of distance. It must never be folded into an
    aggregate as a large value; callers skip it instead.
    """
    if not rings:
        return None
    return min(float(np.hypot(rx - x, ry - y)) for _a, rx, ry in rings)


def scan(sid, step_ms=150, persist_min=2, colour=None, device_inner_min=None,
         drop_self_icon=False):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    ok_area = md.searchable(labels, static=static)
    floor = labels != md.VOID
    lo_gray, hi_gray = md.load_two_state(sid)
    if lo_gray is None:
        print("  no two-state reference in this geometry (built before "
              "2026-08-27) -- falling back to single-reference detection; "
              "border/box-edge false positives are more likely")
    else:
        sgray, hi_gray = lo_gray.astype(np.int16), hi_gray.astype(np.int16)

    cap = cv2.VideoCapture(src["path"])
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = n_frames / fps * 1000.0

    open_tracks: list = []
    closed: list = []
    n_unreadable = 0
    t = 0.0
    while t < duration_ms:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            break
        crop = fr[my0:my1, mx0:mx1]
        dets = []
        if usable(crop, floor) and drawn(crop, sgray, floor):
            dets = [d for d in md.detect(crop, sgray, ok_area, md.DIFF_MIN,
                                         static_gray2=hi_gray)
                    if not colour or d["colour"] == colour]
        else:
            n_unreadable += 1

        # Once per FRAME, not once per new track: every track that matches a
        # detection here wants the same fit, and it is the same fit. Skipped
        # entirely on a frame with nothing to attach it to.
        rings = mm.self_rings(crop, floor) if dets else []

        matched = set()
        for tr in open_tracks:
            best, best_d = None, TRACK_PX
            for i, d in enumerate(dets):
                if i in matched:
                    continue
                dist = float(np.hypot(d["xy"][0] - tr["x"], d["xy"][1] - tr["y"]))
                if dist <= best_d:
                    best, best_d = i, dist
            if best is not None:
                matched.add(best)
                tr["x"], tr["y"] = dets[best]["xy"]
                tr["t_last"] = t
                tr["n"] += 1
                sd = _self_dist(rings, tr["x"], tr["y"])
                if sd is not None:
                    tr["sd"].append(sd)

        still_open = []
        for tr in open_tracks:
            (closed if t - tr["t_last"] > TRACK_GAP_MS else still_open).append(tr)
        open_tracks = still_open

        for i, d in enumerate(dets):
            if i not in matched:
                # Onset-only, on the RAW frame -- see ability_shape.py for why
                # this must not be derived from d's own diff-blob.
                x0i, y0i = int(round(d["xy"][0])), int(round(d["xy"][1]))
                d["device"] = ashape.device_glyph_score(crop, x0i, y0i)
                d["colour_local"], d["colour_frac_local"] = ashape.local_colour(
                    crop, x0i, y0i)
                d["geo_label"] = int(labels[y0i, x0i]) if (0 <= y0i < labels.shape[0]
                                                           and 0 <= x0i < labels.shape[1]) else None
                sd = _self_dist(rings, d["xy"][0], d["xy"][1])
                open_tracks.append({"x": d["xy"][0], "y": d["xy"][1],
                                    "t0": t, "t_last": t, "n": 1, "rep": d,
                                    "sd": [] if sd is None else [sd]})
        t += step_ms
    closed += open_tracks
    cap.release()

    if n_unreadable:
        print(f"  {n_unreadable} of {int(duration_ms // step_ms) + 1} sampled frames "
              f"unreadable (minimap not drawn / not usable there)")

    out = []
    n_device_dropped = 0
    n_self_dropped = 0
    for tr in closed:
        if tr["n"] < persist_min:
            continue
        d = tr["rep"]
        if device_inner_min is not None and d["device"]["inner_edge"] < device_inner_min:
            n_device_dropped += 1
            continue
        # MEDIAN over the track, not the min and not the birth sample. The
        # docstring carries the measurement that chose it: min drops 2 of 5
        # real trapwires because it means "was the player ever here", which is
        # a different question from "is this the player".
        sds = tr["sd"]
        sd = float(np.median(sds)) if sds else None
        sd_min = min(sds) if sds else None
        if drop_self_icon and sd is not None and sd < SELF_ICON_DIST_MIN:
            n_self_dropped += 1
            continue
        bw, bh = d["box"][2], d["box"][3]
        out.append({
            "session_id": sid, "t_ms": round(tr["t0"]),
            "x": int(d["xy"][0]), "y": int(d["xy"][1]),
            "roi": [mx0, my0, mx1, my1],
            "colour": d["colour"], "colour_frac": round(d["colour_frac"], 3),
            "colour_local": d["colour_local"],
            "colour_frac_local": round(d["colour_frac_local"], 3),
            "device_cov": d["device"]["cov"], "device_inner_edge": d["device"]["inner_edge"],
            "device_r": d["device"]["r"],
            "self_icon_dist": round(sd, 2) if sd is not None else None,
            "self_icon_dist_min": round(sd_min, 2) if sd_min is not None else None,
            "self_icon_n": len(sds),
            "geo_label": GEO_LABEL_NAMES.get(d["geo_label"], d["geo_label"]),
            "area": d["area"], "box": list(d["box"]),
            "diff_min": md.DIFF_MIN,
            "aspect": round(max(bw, bh) / max(1, min(bw, bh)), 2),
            "n_observations": tr["n"],
            "duration_ms": round(tr["t_last"] - tr["t0"]),
            "kind": "ability",
            "uncertain": False,
            "by": "claude",
        })
    if n_device_dropped:
        print(f"  --device-inner-min dropped {n_device_dropped} candidate(s) below threshold "
              f"-- do not use this on a clip that can contain an area/ultimate overlay")
    if n_self_dropped:
        print(f"  --drop-self-icon dropped {n_self_dropped} candidate(s) within "
              f"{SELF_ICON_DIST_MIN}px of the fitted self-icon position")
    out.sort(key=lambda r: r["t_ms"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--step-ms", type=int, default=150,
                    help="how densely to sample the clip")
    ap.add_argument("--persist-min", type=int, default=2,
                    help="drop a track seen in fewer than this many sampled frames")
    ap.add_argument("--colour", default=None,
                    help="only keep blobs of this colour, e.g. 'none'; default keeps all, "
                         "since a controlled clip may show a team-coloured controlled ability")
    ap.add_argument("--device-inner-min", type=float, default=None,
                    help="drop candidates below this interior-edge-density score "
                         "(see ability_shape.py). SCOPED TO DEVICE-GLYPH ICONS "
                         "(Cypher, Deadlock) -- do not use on a clip that can contain "
                         "an area/ultimate overlay, which scores low on purpose")
    ap.add_argument("--drop-self-icon", action="store_true",
                    help="drop candidates within SELF_ICON_DIST_MIN of the fitted self-icon "
                         "position -- validated 2026-09-02 on eb10db50b1fb (5/5 real trapwire "
                         "kept, 5/6 self-icon false positives dropped); does NOT catch a real "
                         "object that merely sits near the barrier/wire rendering")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan and report, but do not write the candidate file")
    args = ap.parse_args()

    rows = scan(args.session, step_ms=args.step_ms, persist_min=args.persist_min,
                colour=args.colour, device_inner_min=args.device_inner_min,
                drop_self_icon=args.drop_self_icon)
    print(f"{len(rows)} candidate objects found "
          f"(n_observations {min((r['n_observations'] for r in rows), default=0)}-"
          f"{max((r['n_observations'] for r in rows), default=0)})")
    if args.dry_run:
        return 0

    out_path = STORE / "labels" / "ability_candidates" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
                        encoding="utf-8")
    print(f"wrote {out_path} -- run label_ability.py {args.session} to review and name them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
