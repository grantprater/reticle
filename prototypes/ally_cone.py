r"""Ally icons that carry their own bearing, scored against the ROSTER.

    .\.venv\Scripts\python.exe prototypes\ally_cone.py <session> --scan [--hz 2]
    .\.venv\Scripts\python.exe prototypes\ally_cone.py <session> --score
    .\.venv\Scripts\python.exe prototypes\ally_cone.py <session> --sweep

The collective team viewcone needs a bearing per living teammate, and the ally
channel could not supply one: `l1/minimap` stores per-frame BLOBS with no
identity and no facing, and the blobs are badly contaminated. Rendered by eye
on `a06f04a0059f`:

    32:45   every teammate dead, four blue X marks on the widget   n_allies = 4
     4:59   exactly one teammate alive                             n_allies = 4

So the first question is not "how good is the cone" but "how many of these are
teammates at all", and this file answers it without a single hand label.

THE GROUND TRUTH IS THE ROSTER, and it costs nothing
------------------------------------------------------
`reticle/roster.py` reads both teams' alive counts off the top HUD, per frame,
by portrait detail. A living teammate is ALWAYS drawn on the minimap -- the
widget shows what your team knows, and your team always knows where it is --
so there is an exact identity:

    ally icons on the widget  ==  alive_ally - 1

That is a label-free validator for a detector, produced by a completely
independent reader on a different part of the screen, and it fires on every
sampled frame rather than the fifty a scoreboard offers. It is the same
argument `CLAUDE.md` already makes for auditing the killfeed against the
roster, pointed at a different channel.

**Both readers ride ONE decode** (`passes.run`), because decode is 93% of the
cost and a reader that opens the file for itself is the architectural defect
recorded on 2026-09-05.

What promotes a blob to an icon, and what does NOT
----------------------------------------------------
`minimap.icons` gates on the ring fit: circumference coverage, a non-key
interior (an icon is a surround around a PORTRAIT), and a facing lobe. The
third is the interesting one -- it is simultaneously the test for "is this a
teammate" and the measurement of "where is that teammate looking", which is
why the ally channel and the cone channel are one problem.

**Measured on the first frame rendered, and it is a negative result worth
keeping:** at 4:59 a false positive with no icon in it at all -- a corner where
green scenery tints the semi-transparent widget into the ally hue band --
scored cov 0.50 / inner 0.00 / lobe 0.82, BEATING the one real ally present
(0.31 / 0.03 / 0.43) on every one of the three gates. So tightening them
cannot separate this class, and the sweep below exists to find what can rather
than to pick a number for what cannot.

`detail` is the candidate, and it is borrowed rather than invented: `roster.py`
separates a drawn portrait from an empty slot by LAPLACIAN VARIANCE at 60 of
60, because a portrait is crisp art composited on top while everything else
arrives dimmed and blurred through a semi-transparent panel. An ally icon has
a portrait in it; tinted floor does not. On that one frame it ran 6698 (real
ally) and 3850 (self) against 1534 (the false positive) -- suggestive at n=1
per class, which is why it is RECORDED PER FIT here and swept over thousands
rather than turned into a threshold on the spot.

Every fit is stored with its features so a threshold can be re-swept without
re-decoding -- the label-row convention: carry enough to recompute later.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import passes                                          # noqa: E402
from reticle.minimap import (ally_mask, floor_mask, icons,           # noqa: E402
                             minimap_roi_px, self_mask, widget_drawn,
                             widget_scale)
from reticle.profiles import get_profile                             # noqa: E402
from reticle.roster import RosterReader                              # noqa: E402
from reticle.store import Store                                      # noqa: E402

STORE = Path.home() / "reticle-store"


def _detail(grey_lap: np.ndarray, cx: float, cy: float, r: int) -> float:
    """Laplacian variance over the fitted disc's interior. `roster.py`'s test.

    The 0.62 radius factor is `fit_ring`'s own interior disc, reused rather
    than reinvented so `inner` and `detail` describe the SAME pixels.
    """
    h, w = grey_lap.shape
    rr = max(1, int(round(r * 0.62)))
    y0, y1 = max(0, int(cy) - rr), min(h, int(cy) + rr + 1)
    x0, x1 = max(0, int(cx) - rr), min(w, int(cx) + rr + 1)
    sub = grey_lap[y0:y1, x0:x1]
    return float(sub.var()) if sub.size else 0.0


class AllyIconReader:
    """Every ring fit on the ally and self keys, with its features. No gates.

    Deliberately permissive: `cov_min=0.0`, `inner_max=1.0`,
    `require_facing=False`. A reader that applies the threshold it is being
    used to choose cannot measure it, and re-deciding a gate must never cost
    another decode.
    """

    def __init__(self, profile, wh, med, name="allyicon", hz=2.0, spans=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.box = minimap_roi_px(profile, *wh)
        self.floor = floor_mask(med)
        self.sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)
        self.scale = widget_scale(self.box[2] - self.box[0])
        self.rows: list[dict] = []
        self.n_absent = 0

    def feed(self, smp) -> None:
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        row = {"frame_idx": smp.frame_idx, "t_ms": smp.t_ms,
               "drawn": True, "fits": []}
        # The widget guard is not optional here. Measured over all 27757 frames
        # of a06f04a0059f, widget-absent frames yield 2.6 self candidates each
        # because the key is looking at open scenery -- and a phantom icon
        # carries a phantom BEARING, which then casts a phantom cone.
        if not widget_drawn(crop, self.sgray, self.floor):
            row["drawn"] = False
            self.n_absent += 1
            self.rows.append(row)
            return
        lap = cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
        for key, mask in (("ally", ally_mask(crop)), ("self", self_mask(crop))):
            for f in icons(mask, crop, self.floor, cov_min=0.0, inner_max=1.0,
                           require_facing=False):
                f["key"] = key
                f["detail"] = _detail(lap, f["cx"], f["cy"], f["r"])
                row["fits"].append(f)
        self.rows.append(row)


def _fits_path(sid: str, tag: str = "") -> Path:
    return STORE / "series" / f"{sid}.allycone{tag}.json"


def scan_pass(args) -> int:
    store = Store(STORE)
    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    wh = (int(src["width"]), int(src["height"]))

    tbl = store.read_spans(args.session, args.date) if args.date else None
    if tbl is None:
        # Spans are partitioned by date, and nothing in the manifest names it,
        # so find the partition this session actually landed in.
        for q in (STORE / "l2" / "spans").glob(f"date=*/session={args.session}"):
            args.date = q.parent.name.split("=", 1)[1]
            tbl = store.read_spans(args.session, args.date)
            break
    if tbl is None:
        raise SystemExit(f"no spans for {args.session} -- run `reticle segment` first")
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]
    if not spans:
        raise SystemExit(f"{args.session} has no active spans")
    if args.minutes:
        # The bearing-carry question turns on the SAMPLE RATE, and 2 Hz cannot
        # see a gap under ~500 ms. Clipping the span lets a 15 Hz pass answer
        # the regime the shipped reader actually runs in.
        cap_ms = spans[0][0] + args.minutes * 60000.0
        spans = [(a, min(b, cap_ms)) for a, b in spans if a < cap_ms]

    ctx = passes.SessionContext(store=store, manifest=man, profile=prof, spans=spans)
    med = ctx.static_map()
    ally = AllyIconReader(prof, wh, med, hz=args.hz, spans=spans)
    rost = RosterReader(prof, wh, hz=args.hz, spans=spans)

    total = sum(b - a for a, b in spans) / 1000.0
    print(f"{args.session}: {len(spans)} active spans, {total / 60:.1f} min, "
          f"both readers at {args.hz:g} Hz on ONE decode")

    def progress(n, smp):
        if n % 500 == 0:
            print(f"  {n:6d} frames  t={smp.t_ms / 60000:5.1f} min", flush=True)

    n = passes.run(ctx, [ally, rost], progress=progress)
    print(f"  {n} frames retrieved; widget absent on {ally.n_absent} "
          f"({ally.n_absent / max(n, 1) * 100:.1f}%)")

    out = {"session": args.session, "date": args.date, "hz": args.hz,
           "spans_ms": spans, "scale": ally.scale,
           "frames": ally.rows, "roster": rost.rows}
    p = _fits_path(args.session, args.tag)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    print(f"  wrote {p}")
    return 0


def _load(sid: str, tag: str = "") -> dict:
    p = _fits_path(sid, tag)
    if not p.is_file():
        raise SystemExit(f"no scan for {sid} -- run with --scan first")
    return json.loads(p.read_text(encoding="utf-8"))


def _round_bounds(sid: str):
    """`[(t_start_ms, t_end_ms)]` per round, or None if no HUD is stored."""
    from reticle.rounds import build_rounds
    store = Store(STORE)
    for q in (STORE / "l1" / "hud").glob(f"date=*/session={sid}"):
        date = q.parent.name.split("=", 1)[1]
        tbl = store.read_hud(sid, date)
        if tbl is None:
            continue
        return [(r["t_start_ms"], r["t_end_ms"]) for r in build_rounds(tbl)]
    return None


def _joined(d: dict, skip_lead_ms: float = 0.0, bounds=None):
    """Frames where BOTH readers answered, as `(row, alive_ally)`.

    The join is on `t_ms` exactly, which is safe because both readers were fed
    the same samples in the same pass -- the second reason to run them
    together, after the decode cost.

    **`skip_lead_ms` is not a tuning knob, it is a window correction**, and
    leaving it out is the most repeated mistake in this codebase. `build_rounds`
    bounds INCLUDE the buy phase, and the roster is not drawn for the new round
    during it -- the recorded instance of exactly this went from 5/22 to 40/40
    once the lead-in was dropped. So a frame early in a round is scored against
    a roster describing the PREVIOUS round, and it fails silently by returning
    a plausible number.
    """
    rost = {r["t_ms"]: r["alive_ally"] for r in d["roster"]}
    out = []
    for row in d["frames"]:
        a = rost.get(row["t_ms"])
        if a is None or not row["drawn"]:
            continue
        if bounds is not None:
            t = row["t_ms"]
            if not any(lo + skip_lead_ms <= t < hi for lo, hi in bounds):
                continue
        out.append((row, a))
    return out


def _accept(fits, cov, inner, detail, need_facing=True):
    return [f for f in fits
            if f["key"] == "ally" and f["cov"] >= cov and f["inner"] <= inner
            and f["detail"] >= detail
            and (f["facing"] is not None or not need_facing)]


def _score(d, cov, inner, detail, need_facing=True, skip_lead_ms=0.0, bounds=None):
    """Signed residual against the roster, and the agreement rate."""
    import numpy as np
    res, exact, n = [], 0, 0
    for row, alive in _joined(d, skip_lead_ms, bounds):
        want = max(0, alive - 1)
        got = len(_accept(row["fits"], cov, inner, detail, need_facing))
        res.append(got - want)
        exact += (got == want)
        n += 1
    return n, exact, np.array(res, dtype=float)


def score(args) -> int:
    import numpy as np

    d = _load(args.session, args.tag)
    bounds = _round_bounds(args.session)
    print(f"{args.session}: {len(d['frames'])} sampled frames at {d['hz']:g} Hz")
    if bounds is None:
        print("  no stored HUD -- cannot bound rounds, so ACTIVE SPANS only")
    else:
        print(f"  {len(bounds)} rounds from the stored HUD")

    windows = [("active spans (includes buy phase)", 0.0, None)]
    if bounds is not None:
        windows += [("in round, from its start", 0.0, bounds),
                    ("in round, skipping the first 20 s", 20000.0, bounds)]

    rows = [
        ("raw blobs (= ally_rings)", 0.00, 1.00, 0.0, False),
        ("cov>=.25 inner<=.25", 0.25, 0.25, 0.0, False),
        ("+ facing required", 0.25, 0.25, 0.0, True),
        ("cov>=.30 + facing", 0.30, 0.25, 0.0, True),
        ("+ detail>=2000", 0.25, 0.25, 2000.0, True),
    ]
    for label, skip, b in windows:
        n0 = len(_joined(d, skip, b))
        print(f"\n  WINDOW: {label}   n = {n0}")
        if n0 < 50:
            print("    too few frames to read")
            continue
        j = _joined(d, skip, b)
        want = [max(0, a - 1) for _, a in j]
        print(f"    roster allies alive-1: mean {np.mean(want):.2f}")
        print(f"    {'gate':<26}{'exact':>8}{'mean res':>10}{'median':>8}{'|res|<=1':>10}")
        for name, cov, inner, det, nf in rows:
            n, exact, res = _score(d, cov, inner, det, nf, skip, b)
            print(f"    {name:<26}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
                  f"{np.median(res):8.1f}{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    print("\n  A SYSTEMATIC SIGN is the tell: random error is symmetric, a one-sided")
    print("  residual is a fault. Positive = phantom teammates; negative = missed,")
    print("  or MERGED -- three icons at spawn are one connected component.")
    return 0


def sweep(args) -> int:
    import numpy as np

    d = _load(args.session, args.tag)
    bounds = _round_bounds(args.session)
    skip = 20000.0 if bounds is not None else 0.0
    win = "in round, skipping the first 20 s" if bounds else "active spans"
    n0 = len(_joined(d, skip, bounds))
    print(f"{args.session}: sweeping over {n0} frames -- WINDOW: {win}\n")
    print(f"  {'cov>=':>9}{'exact':>8}{'mean res':>10}{'|res|<=1':>10}")
    for cov in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        n, exact, res = _score(d, cov, 0.25, 0.0, True, skip, bounds)
        print(f"  {cov:9.2f}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    print(f"\n  {'inner<=':>9}{'exact':>8}{'mean res':>10}{'|res|<=1':>10}")
    for inner in (0.10, 0.20, 0.25, 0.35, 0.50, 1.00):
        n, exact, res = _score(d, 0.25, inner, 0.0, True, skip, bounds)
        print(f"  {inner:9.2f}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    print(f"\n  {'detail>=':>9}{'exact':>8}{'mean res':>10}{'|res|<=1':>10}")
    for det in (0, 500, 1000, 2000, 4000):
        n, exact, res = _score(d, 0.25, 0.25, float(det), True, skip, bounds)
        print(f"  {det:9d}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    return 0


def _ang_diff(a, b):
    """Smallest absolute angle between two bearings, degrees, in [0, 180]."""
    return float(abs((a - b + 180.0) % 360.0 - 180.0))


def interp(args) -> int:
    """What is a CARRIED bearing worth? Measured on SELF, the one ground truth.

    `track.Tracker` keeps a track's last known bearing across a frame where the
    lobe fit refused one, and `bearings()` will not offer it unless asked. This
    is the measurement that says whether it should ever be asked for.

    **The self icon is the only bearing with a ground truth**, which is what
    `BACKLOG.md` says to build this against, and its fit answers on ~90% of
    frames -- so the cost of carrying a bearing forward by g milliseconds is
    directly observable as |facing(t+g) - facing(t)| over its own series. No
    hold-out, no labels.

    Two aggregates, per the standing convention, because they answer different
    questions: the median says what a typical carry costs, the p90 says how bad
    the tail is, and a cone drawn from a bearing 90 degrees out is not a
    slightly wrong cone -- it is somewhere else entirely.

    THE NULL IS THE POINT. A bearing carried from a random OTHER moment is the
    control, and it should sit near 90 degrees (the mean absolute difference of
    two independent angles). A carry is worth having only where it is far below
    that; where it is not, the honest answer is to refuse.
    """
    import numpy as np

    d = _load(args.session, args.tag)
    ser = []
    for row in d["frames"]:
        if not row["drawn"]:
            continue
        best = None
        for f in row["fits"]:
            if f["key"] != "self" or f["facing"] is None:
                continue
            if best is None or f["cov"] > best["cov"]:
                best = f
        if best is not None:
            ser.append((row["t_ms"], best["facing"]))
    ser.sort()
    if len(ser) < 30:
        raise SystemExit(f"only {len(ser)} self bearings -- not enough to measure")

    t = np.array([a for a, _ in ser])
    f = np.array([b for _, b in ser])
    print(f"{args.session}: {len(ser)} self bearings over "
          f"{t.min() / 60000:.1f} .. {t.max() / 60000:.1f} min "
          f"(active spans only, sampled at {d['hz']:g} Hz)")

    rng = np.random.default_rng(20260906)   # fixed: the null must be stable
    null = np.array([_ang_diff(f[i], f[j]) for i, j in
                     zip(rng.integers(0, len(f), 4000),
                         rng.integers(0, len(f), 4000))])
    print("")
    print(f"  NULL, a bearing from a random other moment: "
          f"median {np.median(null):.0f}deg  p90 {np.percentile(null, 90):.0f}deg")
    print("")
    print(f"  {'carry (ms)':>12}{'n':>7}{'median':>9}{'p90':>9}"
          f"{'<30deg':>9}{'<56deg':>9}")
    for lo, hi in ((0, 150), (150, 350), (350, 750), (750, 1500), (1500, 3000)):
        errs = []
        for i in range(len(ser)):
            j = i + 1
            while j < len(ser) and t[j] - t[i] < lo:
                j += 1
            if j < len(ser) and lo <= t[j] - t[i] <= hi:
                errs.append(_ang_diff(f[i], f[j]))
        label = f"{lo}-{hi}"
        if len(errs) < 10:
            print(f"  {label:>12}{len(errs):>7}   too few to read")
            continue
        e = np.array(errs)
        print(f"  {label:>12}{len(e):>7}{np.median(e):8.0f}d{np.percentile(e, 90):8.0f}d"
              f"{np.mean(e < 30) * 100:8.0f}%{np.mean(e < 56) * 100:8.0f}%")
    print("")
    print("  56deg is the cone HALF-ANGLE: past it a carried cone and the true")
    print("  cone share no axis at all. Read the p90, not the median.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--interp", action="store_true",
                    help="what a carried bearing is worth, measured on self")
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--minutes", type=float, default=None,
                    help="clip the spans to the first N minutes, which is what makes a 15 Hz pass affordable")
    ap.add_argument("--tag", default="",
                    help="output-file suffix, so a high-rate run does not overwrite the corpus-wide one")
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    if a.scan:
        return scan_pass(a)
    if a.sweep:
        return sweep(a)
    if a.interp:
        return interp(a)
    if a.score or True:
        return score(a)


if __name__ == "__main__":
    sys.exit(main())
