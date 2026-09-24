r"""Mine area abilities from the minimap residual, seeded by nothing but the pixels.

    .\.venv\Scripts\python.exe prototypes\entity_mining_residual.py [--record]

Why this exists, and why it is not `entity_mining_statistical.py`
------------------------------------------------------------------
`entity_mining_statistical.py` recovered Omen's 15 s Dark Cover from two
hand-placed seeds on one session. Promotion needs the seed, the lifetime rule
and the witness to come from somewhere other than the answer. This file is the
2026-09-24 control loop on that question (predictions `entity-mining-promotion`
in the store's `notes/predictions.jsonl`), run on ten radius-extent uses in four
solo demos with tray casts as the independent onset witness.

What the loop found
-------------------
1. **`minimap.detect_ability_discs` is the wrong seed for smokes.** It yields
   3-11 "births" per cast. The same positions recur across sessions: Ascent's
   static dark dots flicker across `BH_MIN` although `static_peaks` should
   exclude them. Every fit it seeded sat on a map dot.
2. **Floor pixels take three levels in a solo clip:** equal to the baked unlit
   base, lit (about 57 grey levels brighter [domain:minimap/vision-gate]), or
   covered by a smoke (about 57 darker). The plateaus are real; seeked frames
   match sequential decode within 0.3-1.9 grey levels.
3. **"New darkening against the pre-cast frame" is confounded by vision:** lit
   floor turning unlit reads as a birth. `lighting.raw_dark`, which compares
   against the unlit baseline, is the right test, and it is production's.
4. **Censoring is not optional.** Omen's ult map hides the widget for 8 s
   during one smoke; a lifetime rule that ignores the gap reports 0 s.
5. With `raw_dark` births (>= 150 px, dark at the centre for 1 s) and a
   per-sample disc state (dark / partial / clear / unobserved), Dark Cover
   lasts 15.25 s and 15.75 s where both ends are seen, and 12.0-19.75 s and
   14.25-16.75 s where one end is censored [domain:abilities/omen-dark-cover].
   The fifth use claimed the same smoke as a cast 1.5 s later: two adjacent
   smokes, and no one-to-one assignment of casts to entities.
6. Jett's Cloudburst reads 2.75-3.0 s twice. Viper's Poison Cloud is dark too
   (4.75-5.0 s here; it is toggled). Viper's Pit darkens the whole widget and
   then the widget disappears, which is a different event, not an object.

What it does not do
-------------------
It assigns casts greedily (earliest birth), so it cannot separate two adjacent
smokes. It emits no events, and `reticle/` does not import it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, lighting, minimap, passes  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

STORE = Path(DEFAULT_STORE)
VERSION = "entity-mining-residual-0.1.0"
#: Radius-extent slots in the solo demos, with the tray slot that casts them.
USES = {"b9558488a607": {"E": "omen:dark cover"}, "e78e75b2d191": {"E": "omen:dark cover"},
        "6bb88dba5d2c": {"Q": "viper:poison cloud", "X": "viper:viper's pit"},
        "ff19748eea8c": {"C": "jett:cloudburst"}}
#: `lighting.MIN_BLOB_PX`'s scale: a smoke is at least a lit region's minimum.
AREA_MIN = 150
#: A component larger than this share of the floor is the widget changing, not an object.
GLOBAL_FRAC = 0.05
STEP_S = 0.25
BIRTH_WINDOW_S = 4.0
PERSIST = 4
HORIZON_S = 45.0


class Session:
    """Frame access returning `raw_dark` with the self icon removed, or None if unobserved."""

    def __init__(self, sid: str):
        man = geometry.manifest(sid, STORE)
        src = man["source"]
        prof = get_profile(man["source_profile"])
        self.box = minimap.minimap_roi_px(prof, int(src["width"]), int(src["height"]))
        ctx = passes.SessionContext(store=Store(STORE), manifest=man, profile=prof)
        self.floor = ctx.floor()
        self.sgray = ctx.sgray()
        with np.load(geometry.path_of(sid, STORE)) as z:
            self.ref = lighting.reference(z)
        self.cap = cv2.VideoCapture(src["path"])
        self.cache: dict[float, np.ndarray | None] = {}

    def dark(self, t: float):
        t = round(t, 2)
        if t not in self.cache:
            self.cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, f = self.cap.read()
            x0, y0, x1, y1 = self.box
            crop = f[y0:y1, x0:x1] if ok else None
            if crop is None or not minimap.widget_drawn(crop, self.sgray, self.floor):
                self.cache[t] = None
            else:
                dk = lighting.raw_dark(crop, self.ref).astype(np.uint8)
                for s in minimap.self_icons(crop, self.floor, require_facing=False):
                    cv2.circle(dk, (int(s["cx"]), int(s["cy"])), int(s["r"]) + 6, 0, -1)
                self.cache[t] = dk.astype(bool)
        return self.cache[t]


def births(s: Session, t_cast: float) -> tuple[list[dict], list[dict]]:
    """Persistent new dark components after a cast, and widget-wide dark events."""
    pre = s.dark(t_cast - 0.75)
    if pre is None:
        return [], [{"reason": "widget_absent_before_cast"}]
    grown = cv2.dilate(pre.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    out, other = [], []
    for dt in np.arange(STEP_S, BIRTH_WINDOW_S + 1e-6, STEP_S):
        d = s.dark(t_cast + dt)
        if d is None:
            continue
        new = cv2.morphologyEx((d & ~grown).astype(np.uint8), cv2.MORPH_OPEN,
                               np.ones((3, 3), np.uint8))
        n, _, st, cen = cv2.connectedComponentsWithStats(new, 8)
        for i in range(1, n):
            if st[i, 4] < AREA_MIN:
                continue
            t = round(t_cast + dt, 2)
            if st[i, 4] > GLOBAL_FRAC * s.floor.sum():
                other.append({"t": t, "area": int(st[i, 4]), "reason": "widget_wide_dark"})
                continue
            cx, cy = int(cen[i][0]), int(cen[i][1])
            later = [s.dark(t + k * STEP_S) for k in range(1, PERSIST + 1)]
            if any(l is None or not l[cy, cx] for l in later):
                continue
            out.append({"t": t, "cx": float(cen[i][0]), "cy": float(cen[i][1]),
                        "area": int(st[i, 4]), "r_eq": float(np.sqrt(st[i, 4] / np.pi))})
    return out, other


def states(s: Session, b: dict, t_end: float) -> tuple[np.ndarray, str]:
    """Per sample: D dark, p partial, c clear, u unobserved, inside 0.7 r of the birth."""
    H, W = s.floor.shape
    Y, X = np.ogrid[:H, :W]
    disc = ((X - b["cx"]) ** 2 + (Y - b["cy"]) ** 2 <= (0.7 * b["r_eq"]) ** 2) & s.ref.known
    ts = np.arange(b["t"], t_end, STEP_S)
    out = []
    for t in ts:
        d = s.dark(t)
        if d is None or not disc.any():
            out.append("u")
            continue
        fr = d[disc].mean()
        out.append("D" if fr >= 0.5 else "c" if fr < 0.1 else "p")
    return ts, "".join(out)


def lifetime(ts: np.ndarray, st: str) -> dict:
    """First fully dark sample to last dark before >= 1 s clear, with censoring.

    An unobserved sample adjacent to an end makes that end an interval, never a
    point: a missing frame is not evidence the smoke persisted or ended.
    """
    first = st.find("D")
    if first < 0:
        return {"status": "never_dark"}
    end = st.find("c" * PERSIST, first)
    if end < 0:
        return {"status": "no_end_observed", "onset": float(ts[first])}
    last = st.rfind("D", first, end)
    on_lo = on_hi = float(ts[first])
    k = first - 1
    while k >= 0 and st[k] == "u":
        k -= 1
    if k < first - 1:
        on_lo = float(ts[k + 1])
    off_lo, off_hi = float(ts[last]), float(ts[end])
    if "u" not in st[last:end]:
        off_hi = float(ts[last]) + STEP_S
    gaps = st.count("u", first, last)
    return {"status": "censored" if (on_lo < on_hi or off_hi - off_lo > STEP_S) else "observed",
            "onset": [on_lo, on_hi], "expiry": [off_lo, off_hi],
            "life_s": [round(off_lo - on_hi, 2), round(off_hi - on_lo, 2)],
            "unobserved_inside": gaps}


def mine_demos(record: bool = False) -> list[dict]:
    rows = []
    for sid, slots in USES.items():
        s = Session(sid)
        casts = json.loads(sorted((STORE / "casts").glob(f"{sid}.step*.json"))[0]
                           .read_text(encoding="utf-8"))
        for t_cast, slot, *_ in casts:
            if slot not in slots:
                continue
            got, other = births(s, t_cast)
            row = {"session": sid, "ability": slots[slot], "cast": t_cast,
                   "births": len(got), "other": other}
            if got:
                b = min(got, key=lambda b: (b["t"], -b["area"]))
                ts, st = states(s, b, t_cast + HORIZON_S)
                row.update({"seed": [round(b["cx"]), round(b["cy"]), b["t"]],
                            "life": lifetime(ts, st)})
            rows.append(row)
            life = row.get("life", {})
            print(f"{sid} {row['ability']:<20} cast {t_cast:5.1f}  seed {row.get('seed')}  "
                  f"{life.get('status', '-'):<16} life {life.get('life_s')}  other {other}")
        s.cap.release()
    if record:
        from reticle import metrics
        seeds = [tuple(r["seed"][:2]) for r in rows if r.get("seed")]
        # A seed two casts share is one entity; neither cast is credited with it.
        unique = [r for r in rows if r.get("seed") and seeds.count(tuple(r["seed"][:2])) == 1]
        dc = [r["life"]["life_s"] for r in unique
              if r["ability"] == "omen:dark cover" and r["life"].get("life_s")]
        metrics.record("entity_mining_residual", part="solo-demo",
                       values={"uses": len(rows), "seeded": len(seeds),
                               "dark_cover_unique_contains_15": sum(lo - 1 <= 15 <= hi + 1 for lo, hi in dc),
                               "dark_cover_n": sum(r["ability"] == "omen:dark cover" for r in rows),
                               "duplicate_seeds": len(seeds) - len(set(seeds))},
                       deps={"version": VERSION, "sessions": sorted(USES),
                             "lighting": lighting.LIGHTING_VERSION},
                       note="tray casts as onset witness; domain 15 s as Dark Cover duration")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    mine_demos(ap.parse_args(argv).record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
