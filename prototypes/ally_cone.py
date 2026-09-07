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


def _fits_path(sid: str) -> Path:
    return STORE / "series" / f"{sid}.allycone.json"


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
    p = _fits_path(args.session)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    print(f"  wrote {p}")
    return 0


def _load(sid: str) -> dict:
    p = _fits_path(sid)
    if not p.is_file():
        raise SystemExit(f"no scan for {sid} -- run with --scan first")
    return json.loads(p.read_text(encoding="utf-8"))


def _joined(d: dict):
    """Frames where BOTH readers answered, as `(row, alive_ally)`.

    The join is on `t_ms` exactly, which is safe because both readers were fed
    the same samples in the same pass -- that is the second reason to run them
    together, after the decode cost.
    """
    rost = {r["t_ms"]: r["alive_ally"] for r in d["roster"]}
    out = []
    for row in d["frames"]:
        a = rost.get(row["t_ms"])
        if a is None or not row["drawn"]:
            continue
        out.append((row, a))
    return out


def _accept(fits, cov, inner, detail, need_facing=True):
    return [f for f in fits
            if f["key"] == "ally" and f["cov"] >= cov and f["inner"] <= inner
            and f["detail"] >= detail
            and (f["facing"] is not None or not need_facing)]


def _score(d, cov, inner, detail, need_facing=True):
    """Signed residual against the roster, and the agreement rate."""
    res, exact, n = [], 0, 0
    for row, alive in _joined(d):
        want = max(0, alive - 1)
        got = len(_accept(row["fits"], cov, inner, detail, need_facing))
        res.append(got - want)
        exact += (got == want)
        n += 1
    return n, exact, np.array(res, dtype=float)


def score(args) -> int:
    d = _load(args.session)
    j = _joined(d)
    print(f"{args.session}: {len(d['frames'])} sampled frames, "
          f"{len(j)} with the widget drawn AND a roster read")
    span = [row["t_ms"] for row, _ in j]
    if span:
        print(f"  window: {min(span) / 60000:.1f} .. {max(span) / 60000:.1f} min "
              f"(active spans only -- the roster says nothing off-round)")

    raw = [len([f for f in row["fits"] if f["key"] == "ally"]) for row, _ in j]
    want = [max(0, a - 1) for _, a in j]
    print(f"\n  roster says allies alive-1:  mean {np.mean(want):.2f}")
    print(f"  RAW ally fits (no gate):     mean {np.mean(raw):.2f}")

    print(f"\n  {'gate':<34}{'exact':>8}{'mean res':>10}{'median':>8}"
          f"{'|res|<=1':>10}")
    rows = [
        ("raw blobs (ally_rings equivalent)", 0.0, 1.0, 0.0, False),
        ("cov>=.30 inner<=.25", 0.30, 0.25, 0.0, False),
        ("+ facing required", 0.30, 0.25, 0.0, True),
        ("+ detail>=2000", 0.30, 0.25, 2000.0, True),
        ("+ detail>=3000", 0.30, 0.25, 3000.0, True),
    ]
    for label, cov, inner, det, nf in rows:
        n, exact, res = _score(d, cov, inner, det, nf)
        print(f"  {label:<34}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.median(res):8.1f}{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    print("\n  A SYSTEMATIC SIGN is the tell: random error is symmetric, a\n"
          "  one-sided residual is a fault. Positive = phantom teammates,\n"
          "  negative = missed or merged (three icons at spawn are ONE blob).")
    return 0


def sweep(args) -> int:
    d = _load(args.session)
    print(f"{args.session}: sweeping the detail floor at cov>=0.30, "
          f"inner<=0.25, facing required\n")
    print(f"  {'detail>=':>9}{'exact':>8}{'mean res':>10}{'|res|<=1':>10}")
    for det in (0, 500, 1000, 1500, 2000, 2500, 3000, 4000, 6000):
        n, exact, res = _score(d, 0.30, 0.25, float(det), True)
        print(f"  {det:9d}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    print(f"\n  {'cov>=':>9}{'exact':>8}{'mean res':>10}{'|res|<=1':>10}")
    for cov in (0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        n, exact, res = _score(d, cov, 0.25, 0.0, True)
        print(f"  {cov:9.2f}{exact / max(n, 1) * 100:7.1f}%{res.mean():10.2f}"
              f"{np.mean(np.abs(res) <= 1) * 100:9.1f}%")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    if a.scan:
        return scan_pass(a)
    if a.sweep:
        return sweep(a)
    if a.score or True:
        return score(a)


if __name__ == "__main__":
    sys.exit(main())
