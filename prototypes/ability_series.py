r"""Per-frame time series at a minimap position -- the substrate the temporal features need.

    .\.venv\Scripts\python.exe prototypes\ability_series.py <session> [--from-labels] [--out DIR]
    .\.venv\Scripts\python.exe prototypes\ability_series.py --all-demo

Phase 1 of `docs/ability-temporal.html`. Nothing here is a feature; this is the
data shape every feature in that document needs and none of them could be built
without.

Why this module exists at all
------------------------------
**Every temporal feature in this repo is a SCALAR SUMMARY of a track.**
`n_observations` and `duration_ms` are lengths, `motion()` is a displacement,
`drawn()`/`usable()` are booleans, `static_gray`/`two_state_gray` collapse time
per pixel. Nothing anywhere looks at the SHAPE of a signal over time -- and both
of the false-positive classes the player named off the ranked gallery ("fragments of
viewcone", "tiny cracks in the minimap") live in that shape rather than in any
of those summaries.

That gap is not because the ideas were hard. It is because the data shape did
not exist. `scan_ability_clip.scan()` keeps a representative dict from the frame
that opened a track and three scalars; `ability_cone.features_at()` reads
exactly one frame per row. Neither can answer "what did this pixel do over
time", so this does that once and writes it down.

Three design decisions, each inherited from a mistake already recorded here
---------------------------------------------------------------------------

**1. Queries are `(t_ms, x, y)`, and everything is RECOMPUTED. Never re-scan.**
This is `ability_eval.label_rows`'s lesson applied to time, and it is the
load-bearing decision in the module. The ability label store's key is unstable,
so re-scanning a labelled session ORPHANS the answers on it -- NOTES names four
sessions that must never be re-scanned (`2ba870ccbd50`, `eb10db50b1fb`,
`d95cfad5693a`, `79a706a7ce4c`), and those four are exactly the ones carrying
every ability label the player has ever given. A design that needed a re-scan to
produce temporal features could therefore be scored against NO labels at all. A
label row carries the answer and `(t_ms, x, y)`, which is enough to find the
pixel again, so `--from-labels` reads the label file directly and this module
never writes to either store.

**2. Sequential decode, one pass per clip.** Both existing tools call
`cap.set(CAP_PROP_POS_FRAMES)` per sample. A window of frames around every query
would be thousands of seeks, and CLAUDE.md already states the general form of
this ("seeking is expensive in H.264 and contiguous decoding is cheap -- decode
ranges, not scattered frames"). There is a correctness half as well: OpenCV's
frame-exact seeking on H.264 is not reliable, which does not matter when you
sample one frame per row and matters a great deal when the measurement IS the
difference between consecutive frames. So the video is read front to back once
and every query is filled from the same pass.

**3. Native frame rate, not `scan_ability_clip`'s 150 ms.** The candidate scan
samples at 6.7 Hz because it is looking for placements. Two of the features this
feeds -- intra-patch animation variance, and repeat structure at a position --
are measuring things that can be FASTER than that, and a signal sampled below
its own rate aliases into what looks like broadband noise. That would make the
animation feature measure the opposite of what it is for. `--step` defaults to
every frame; the corpus is 27 clips of 20-64 s at 60 fps, about 18 minutes
total, so decoding all of it is affordable and the alias risk is not worth
taking to save it.

What one series row holds, and why each field
-----------------------------------------------
Per query position, per sampled frame:

    g_mean, g_max, g_min   the patch's own grey level. The raw material for
                           intra-patch variance -- a crack, once lit, is static;
                           an animating ultimate is not
    dark, bright           the two-state interval residual, `max(lo-g,0)` and
                           `max(g-hi,0)` over the patch. SPLIT, never collapsed:
                           `minimap_dynamic.detect` computes their max and that
                           conflates a black device with a brightness lift
    dark_n, bright_n       the same two divided by the per-state noise map, which
                           is what Phase 0 added `sd_lo`/`sd_hi` for. The ability
                           classes differ ~8x in contrast, so an absolute floor
                           that keeps the sensors deletes Orbital Strike
    cone                   does the fitted self-cone cover THIS pixel this frame
    cone_ok                did the cone fit at all. A frame with no fit is
                           absence of evidence and must be dropped from a
                           conditional, never folded in as "not covered" --
                           the fit fails when the widget is occluded, which is
                           when candidates are born, so folding it in would bias
                           in the worst available direction
    self_x, self_y, self_d the self track's fitted position, and the distance
                           from it to this query. Feeds the player-anchored
                           test, which marks the drone HUD overlay, the audio
                           ring and Vyse's ultimate DERIVABLE rather than
                           detectable
    detect                 did `minimap_dynamic.detect` fire within DETECT_PX.
                           The presence series that repeat-structure counts
                           onsets in
    usable, drawn          is the widget readable at all this frame

`t_ms` is stored once per frame for the whole clip, not per row -- every series
shares one time axis by construction, which is what makes them comparable
without a join.

What this module deliberately does NOT do
------------------------------------------
No thresholds, no scores, no verdicts. It is the substrate, and the features
that read it are scored separately -- against the existing labels as a
FALSIFICATION gate only, because those 254 rows are five ability classes from
three agents and that is the same narrow population whose failure to transfer
killed the ranked corpus. See the design doc's SS6 for the three label-free
scores that are honest before a labelling pass exists.

Cost, measured on `c0b63335e635` (Tejo, 38.5 s, 45 candidates)
---------------------------------------------------------------
The cone fit dominates by an order of magnitude -- it raycasts 240 rays per
frame -- so `--cone-step` samples it more coarsely than the pixel reads and
holds the last answer between fits. That is legitimate for a coverage question
(the cone sweeps continuously; it does not teleport) and it is the difference
between a corpus pass of minutes and one of hours. `--no-cone` skips it
entirely for the features that do not need it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.profiles import get_profile                              # noqa: E402
from reticle import minimap as mm                                     # noqa: E402
import minimap_dynamic as md                                          # noqa: E402
import minimap_cone as mc                                             # noqa: E402
from minimap_icons import floor_mask                                  # noqa: E402
from minimap_temporal import usable, drawn                            # noqa: E402

STORE = Path.home() / "reticle-store"
CAND = STORE / "labels" / "ability_candidates"
LAB = STORE / "labels" / "ability"
OUT = STORE / "series"

#: Half-width of the patch read at each query, in source pixels. 7 gives a 15x15
#: window -- matched to `ability_cone.WIN` so `dark`/`bright` here mean the same
#: thing they mean there, and comparisons between the two are like-for-like.
WIN = 7

#: A `detect` blob counts as "present at this query" within this distance.
#: Same radius `scan_ability_clip.TRACK_PX` uses for "is this the same object",
#: for the same reason: it is the scale at which two readings of one object stop
#: being distinguishable on this widget.
DETECT_PX = 10

#: Refit the cone every Nth sampled frame and hold the answer between fits.
#: See the module docstring on cost. At 60 fps this is ~8 Hz, far faster than a
#: player turns through a 112-degree wedge.
CONE_EVERY = 8


def _queries_from_candidates(sid):
    f = CAND / f"{sid}.jsonl"
    if not f.exists():
        return []
    out = []
    for i, line in enumerate(open(f, encoding="utf-8")):
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({"qid": f"c{i}", "x": int(r["x"]), "y": int(r["y"]),
                    "t_ms": int(r["t_ms"]), "src": "candidate"})
    return out


def _queries_from_labels(sid):
    """the answers, with no candidate join -- see `ability_eval.label_rows`.

    The truth field is carried through so a scorer does not have to re-open the
    label file and re-join by position. `uncertain` rows are kept and marked
    rather than dropped: they are excluded from SCORING, but a series is a
    measurement and there is no reason to refuse to measure one.
    """
    f = LAB / f"{sid}.jsonl"
    if not f.exists():
        return []
    out = []
    for i, line in enumerate(open(f, encoding="utf-8")):
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({"qid": f"l{i}", "x": int(r["x"]), "y": int(r["y"]),
                    "t_ms": int(r["t_ms"]), "src": "label",
                    "true": (not r.get("not_ability")),
                    "uncertain": bool(r.get("uncertain")),
                    "agent": r.get("agent"), "ability": r.get("ability")})
    return out


def series(sid, from_labels=False, step=1, use_cone=True, cone_every=CONE_EVERY,
           progress=False):
    """One sequential pass over the clip; returns (queries, time axis, fields).

    `fields` is a dict of (n_queries, n_frames) arrays, one per measurement in
    the docstring above. Empty query list returns empty arrays rather than
    raising -- a clip with no candidates is a legitimate answer, not an error.
    """
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)

    z = np.load(STORE / "geometry" / f"{sid}.npz")
    labels, static = z["labels"], z["static"]
    if "lo_gray" not in z.files:
        raise SystemExit(f"{sid}: geometry has no two-state reference -- rebuild it")
    lo = z["lo_gray"].astype(np.float32)
    hi = z["hi_gray"].astype(np.float32)
    # Phase 0's per-state noise. Absent on geometry built before 2026-09-04;
    # the normalised fields are then simply the unnormalised ones, which is
    # honest -- a divisor of 1 is "no noise model", not "noise is 1".
    if "sd_lo" in z.files:
        sd_lo = np.maximum(z["sd_lo"].astype(np.float32), md.SD_FLOOR)
        sd_hi = np.maximum(z["sd_hi"].astype(np.float32), md.SD_FLOOR)
    else:
        print(f"  {sid}: geometry predates sd_lo/sd_hi -- *_n fields will equal "
              f"their unnormalised counterparts")
        sd_lo = sd_hi = np.ones_like(lo)

    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    ok_area = md.searchable(labels, static=static)

    # TWO floors, deliberately, because this repo has three conventions for the
    # `floor` argument and picking one would silently break a comparison:
    #
    #   reticle/cli.py        floor_mask(med)              the SHIPPED self track
    #   ability_cone.py       floor_mask(static, dilate=1) where the 89% cone
    #                                                      yield was measured
    #   scan_ability_clip.py  labels != VOID               where self_icon_dist is
    #
    # `self_d` here has to be readable against the stored `self_icon_dist`, so
    # the ring fit uses that module's floor; the cone has to be readable against
    # the 89%-of-frames yield figure everything downstream budgets from, so it
    # uses ability_cone's. Using one floor for both would make one of those two
    # numbers incomparable, and it would not be obvious which.
    # The divergence is itself a latent defect -- recorded in NOTES, not fixed here.
    floor_rings = labels != md.VOID
    floor_cone = floor_mask(static, dilate=1)

    qs = (_queries_from_labels(sid) if from_labels else _queries_from_candidates(sid))
    hgt, wid = lo.shape
    # Clamp once rather than per frame. A query off the widget is a real thing
    # (`geo_label` VOID leaks are recorded in scan_ability_clip) and must not
    # crash the pass; it gets a clamped patch and its geometry says why.
    for q in qs:
        q["x"] = int(np.clip(q["x"], 0, wid - 1))
        q["y"] = int(np.clip(q["y"], 0, hgt - 1))
    slices = [(slice(max(0, q["y"] - WIN), min(hgt, q["y"] + WIN + 1)),
               slice(max(0, q["x"] - WIN), min(wid, q["x"] + WIN + 1))) for q in qs]

    cap = cv2.VideoCapture(src["path"])
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    n_samp = len(range(0, n_frames, step))
    nq = len(qs)

    F = {k: np.zeros((nq, n_samp), np.float32) for k in
         ("g_mean", "g_max", "g_min", "dark", "bright", "dark_n", "bright_n",
          "self_x", "self_y", "self_d")}
    F["cone"] = np.zeros((nq, n_samp), bool)
    F["detect"] = np.zeros((nq, n_samp), bool)
    cone_ok = np.zeros(n_samp, bool)
    frame_usable = np.zeros(n_samp, bool)
    t_ms = np.zeros(n_samp, np.float32)

    cone = None
    last_fit = -10 ** 9
    t0 = time.time()
    fi = si = 0
    while si < n_samp:
        got, fr = cap.read()
        if not got:
            break
        if fi % step:
            fi += 1
            continue
        t_ms[si] = fi / fps * 1000.0
        crop = fr[my0:my1, mx0:mx1]
        if crop.shape[:2] != lo.shape:
            raise SystemExit(f"{sid}: ROI {crop.shape[:2]} != geometry {lo.shape} "
                             f"-- wrong profile or stale geometry")
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ok = bool(usable(crop, floor_rings) and drawn(crop, sgray, floor_rings))
        frame_usable[si] = ok

        if ok:
            dark = np.maximum(lo - g, 0.0)
            bright = np.maximum(g - hi, 0.0)
            dets = md.detect(crop, sgray, ok_area, md.DIFF_MIN, static_gray2=hi.astype(np.int16))
            dxy = np.array([d["xy"] for d in dets], np.float32) if dets else np.zeros((0, 2), np.float32)

            rings = mm.self_rings(crop, floor_rings)
            if rings:
                _a, sx, sy = max(rings, key=lambda r: r[0])
            else:
                sx = sy = np.nan

            # The cone is the expensive read; refit on a schedule and hold the
            # last answer between fits. `cone_ok` records whether THIS frame's
            # coverage rests on a fit at all, so a conditional can drop the
            # frames where it does not.
            if use_cone and rings and (si - last_fit) >= cone_every:
                last_fit = si
                try:
                    cone = mc.self_cone(crop, floor_cone, labels, int(sx), int(sy))
                except Exception:
                    cone = None
            cone_ok[si] = bool(use_cone and cone is not None)

            for k, (q, sl) in enumerate(zip(qs, slices)):
                p = g[sl]
                F["g_mean"][k, si] = p.mean()
                F["g_max"][k, si] = p.max()
                F["g_min"][k, si] = p.min()
                F["dark"][k, si] = dark[sl].max()
                F["bright"][k, si] = bright[sl].max()
                F["dark_n"][k, si] = (dark[sl] / sd_lo[sl]).max()
                F["bright_n"][k, si] = (bright[sl] / sd_hi[sl]).max()
                F["self_x"][k, si] = sx
                F["self_y"][k, si] = sy
                F["self_d"][k, si] = (np.hypot(sx - q["x"], sy - q["y"])
                                      if rings else np.nan)
                if cone is not None:
                    F["cone"][k, si] = bool(cone[q["y"], q["x"]])
                if len(dxy):
                    d2 = ((dxy[:, 0] - q["x"]) ** 2 + (dxy[:, 1] - q["y"]) ** 2).min()
                    F["detect"][k, si] = bool(d2 <= DETECT_PX ** 2)
        else:
            for k in ("self_x", "self_y", "self_d"):
                F[k][:, si] = np.nan

        si += 1
        fi += 1
        if progress and si % 300 == 0:
            print(f"    {si}/{n_samp} frames  {time.time() - t0:.0f}s", flush=True)
    cap.release()

    if si < n_samp:                       # decoder stopped short of the header count
        t_ms = t_ms[:si]
        cone_ok, frame_usable = cone_ok[:si], frame_usable[:si]
        F = {k: v[:, :si] for k, v in F.items()}
    F["cone_ok"] = cone_ok
    F["usable"] = frame_usable
    return qs, t_ms, F


def write(sid, qs, t_ms, F, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{sid}.npz"
    np.savez_compressed(p, t_ms=t_ms, queries=np.array(json.dumps(qs)), **F)
    return p


def load(sid, out_dir: Path = OUT):
    """(queries, t_ms, fields) back off disk, queries as real dicts."""
    z = np.load(out_dir / f"{sid}.npz", allow_pickle=False)
    qs = json.loads(str(z["queries"]))
    F = {k: z[k] for k in z.files if k not in ("t_ms", "queries")}
    return qs, z["t_ms"], F


def summarise(sid, qs, t_ms, F):
    """Enough to tell a working pass from a broken one, and nothing more.

    Deliberately not a score. Every number here is a coverage or sanity figure
    -- how much of the clip was readable, how often the cone answered, whether
    the series actually vary -- because a threshold printed beside them would
    be read as a result and there are no labels behind one yet.
    """
    n = len(t_ms)
    print(f"{sid}: {len(qs)} queries x {n} frames "
          f"({t_ms[-1] / 1000:.1f}s @ {n / max(t_ms[-1] / 1000, 1e-9):.0f} Hz)")
    print(f"   widget usable {100 * F['usable'].mean():.1f}%   "
          f"cone answered {100 * F['cone_ok'].mean():.1f}% of frames")
    if not len(qs):
        return
    det = F["detect"].mean(axis=1)
    cov = F["cone"].mean(axis=1)
    sd = F["g_mean"].std(axis=1)
    sdist = np.nanmedian(np.where(np.isnan(F["self_d"]), np.nan, F["self_d"]), axis=1)
    print(f"   present  (detect fired) per query: p50 {100 * np.median(det):.1f}%  "
          f"max {100 * det.max():.1f}%")
    print(f"   cone covers query:                 p50 {100 * np.median(cov):.1f}%  "
          f"max {100 * cov.max():.1f}%")
    print(f"   patch grey SD over time:           p50 {np.median(sd):.2f}  "
          f"max {sd.max():.2f}")
    with np.errstate(invalid="ignore"):
        print(f"   median distance to self icon:      p50 {np.nanmedian(sdist):.1f}px  "
              f"min {np.nanmin(sdist):.1f}px")


def demo_sessions():
    out = []
    for f in sorted((STORE / "manifests").glob("*.json")):
        man = json.loads(f.read_text())
        if "ability-demo" in man.get("tags", []):
            out.append(f.stem)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?")
    ap.add_argument("--all-demo", action="store_true",
                    help="every session tagged ability-demo")
    ap.add_argument("--from-labels", action="store_true",
                    help="query the label rows instead of the candidate file. "
                         "Needs no candidate join, so it reaches the sessions whose "
                         "candidate keys are orphaned -- see the module docstring")
    ap.add_argument("--step", type=int, default=1,
                    help="sample every Nth frame; 1 (default) is native rate. "
                         "Raising this re-introduces the aliasing this module "
                         "exists to avoid -- see the docstring before you do")
    ap.add_argument("--no-cone", action="store_true",
                    help="skip the cone fit entirely; much faster, and correct "
                         "for any feature that does not need coverage")
    ap.add_argument("--cone-every", type=int, default=CONE_EVERY,
                    help="refit the cone every Nth sampled frame, holding the "
                         "answer between fits")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true", help="summarise, write nothing")
    args = ap.parse_args()

    sids = demo_sessions() if args.all_demo else ([args.session] if args.session else [])
    if not sids:
        ap.error("give a session or --all-demo")
    out_dir = Path(args.out)
    for sid in sids:
        t0 = time.time()
        qs, t_ms, F = series(sid, from_labels=args.from_labels, step=args.step,
                             use_cone=not args.no_cone, cone_every=args.cone_every,
                             progress=len(sids) == 1)
        summarise(sid, qs, t_ms, F)
        if not args.dry_run:
            p = write(sid, qs, t_ms, F, out_dir)
            print(f"   wrote {p}  ({p.stat().st_size / 1e6:.1f} MB, "
                  f"{time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
