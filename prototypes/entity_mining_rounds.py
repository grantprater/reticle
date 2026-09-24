r"""Ungated minimap dark-region tracks over whole match rounds.

    .\.venv\Scripts\python.exe prototypes\entity_mining_rounds.py

The match check for `entity_mining_residual.py` (predictions R1-R4 under
`entity-mining-promotion`). A match has no tray cast for anyone else's smoke,
so births are ungated: every `lighting.raw_dark` component of at least 150 px,
matched frame to frame at 4 Hz, alive at least 1 s. Rounds 5, 10, 17 and 22 of
`a06f04a0059f`: the 5th and 10th of each half, which the player chose as
ult-likely.

Reviewed by eye, 2026-09-24. The first ungated run gave 16 tracks: 5 smokes,
one smoke split in three, and the rest enemy icons, an ally icon and merged
ally death marks. Three changes, each from looking, removed every non-smoke
track without touching the lifetime rule:

1. **Occluders from their owners** (self and ally icons from `minimap`, death
   marks from `adjudication.death`, and a local red-ring rule for enemy icons,
   which no module owns) are removed before components form, and a track
   whose disc is covered is unobserved, not gone.
2. **After birth a track is judged by the dark share of its own disc.** A
   smoke's hatched texture keeps its component near `AMIN`, and re-detection
   split one smoke into three.
3. **Smoke evidence is dark AND grey.** Smoke dark pixels measured saturation
   median 0; two merged blue death marks, which the death owner's 15-150 px
   area range misses, measured 162.

Result: 6 tracks, all smokes. Observed ends read 18.0 s three times and
censored ends 16.75-17.75 s. Enemy smokes are not drawn
[domain:abilities/enemy-smokes-not-on-minimap], so these are the ally Miks's,
whose smoke lasts 16.75 s [domain:abilities/miks-smoke-duration]: the tracker
reads about 1.25 s long. An enemy smoke shows only as missing light in an
ally's cone [domain:minimap/enemy-smokes-block-cones], which this does not read.
"""
import sys, json, pathlib
import cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from reticle import geometry, lighting, minimap, passes, decode
from reticle.store import Store, DEFAULT_STORE
from reticle.profiles import get_profile
import pyarrow.parquet as pq
R = pathlib.Path(DEFAULT_STORE); SP = R / "analysis" / "entity_mining"
SP.mkdir(parents=True, exist_ok=True)
sid = "a06f04a0059f"; ROUNDS = [5, 10, 17, 22]; HZ = 4.0; AMIN = 150; GONE = 4
man = geometry.manifest(sid, R); src = man["source"]; prof = get_profile(man["source_profile"])
x0, y0, x1, y1 = minimap.minimap_roi_px(prof, int(src["width"]), int(src["height"]))
ctx = passes.SessionContext(store=Store(R), manifest=man, profile=prof)
floor = ctx.floor(); sgray = ctx.sgray()
with np.load(geometry.path_of(sid, R)) as z: ref = lighting.reference(z)
rounds = {r["round_no"]: r for r in pq.read_table(next((R/"l2/rounds").rglob(f"session={sid}/rounds.parquet"))).to_pylist()}
spans = [(rounds[k]["t_start_ms"], rounds[k]["t_end_ms"]) for k in ROUNDS]
from reticle.adjudication import death
base = ctx.map_reference()
tracks, live, samples = [], [], 0
ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
H, W = floor.shape; YY, XX = np.ogrid[:H, :W]
#: Enemy icons have no owner (`reticle ownership "enemy icon"` names none), so
#: this prototype keys their red ring locally and dilates it over the portrait.
RED_S_MIN, RED_V_MIN, ENEMY_FILL_PX = 90, 120, 8
SMOKE_SAT_MAX = 60


def occluders(crop):
    """Pixels something else draws over the floor, each from its owner."""
    occ = np.zeros((H, W), np.uint8)
    for s in minimap.self_icons(crop, floor, require_facing=False):
        cv2.circle(occ, (int(s["cx"]), int(s["cy"])), int(s["r"]) + 6, 1, -1)
    for a in minimap.ally_icons(crop, floor, static=base, require_facing=False):
        cv2.circle(occ, (int(a["cx"]), int(a["cy"])), int(a["r"]) + 4, 1, -1)
    blue, red = death.extract_minimap_death_marks(crop, floor)
    for _, x, y in blue + red:
        cv2.circle(occ, (int(x), int(y)), 10, 1, -1)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    redpx = (((h < 10) | (h > 165)) & (sat > RED_S_MIN) & (v > RED_V_MIN)).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ENEMY_FILL_PX + 1,) * 2)
    return (occ | cv2.dilate(redpx, k)).astype(bool)


def close(tr, why):
    tr["end"] = why
    tracks.append(tr)


prev_rnd = None
for who, smp in decode.sample_windows(src["path"], float(src["fps"]), {"dark": (HZ, spans)}):
    t = smp.t_ms / 1000.0; samples += 1
    rnd = next(k for k in ROUNDS if rounds[k]["t_start_ms"] <= smp.t_ms <= rounds[k]["t_end_ms"] + 1)
    if prev_rnd is not None and rnd != prev_rnd:
        for tr in live: close(tr, "censored:round_window_end")
        live = []
    prev_rnd = rnd
    crop = smp.frame[y0:y1, x0:x1]
    if not minimap.widget_drawn(crop, sgray, floor):
        for tr in live: tr["unseen_after"] = t              # unobserved: nothing ages
        continue
    occ = occluders(crop)
    # A smoke is grey: its dark pixels measured saturation median 0 (p90 <= 12)
    # on two clean discs, against 162 on merged blue death marks the death
    # owner's area filter misses. Dark AND achromatic is the smoke evidence.
    grey_dark = lighting.raw_dark(crop, ref) & (cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1] < SMOKE_SAT_MAX)
    dk = (grey_dark & ~occ).astype(np.uint8)
    lit = lighting.raw_lit(crop, ref)
    dk = cv2.morphologyEx(dk, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lbl, st, cen = cv2.connectedComponentsWithStats(dk, 8)
    comps = []
    for i in range(1, n):
        a = int(st[i, 4])
        if a < AMIN: continue
        if a > 0.05 * floor.sum(): comps.append({"global": True, "area": a}); continue
        m = (lbl == i).astype(np.uint8); annulus = (cv2.dilate(m, ring) > 0) & ~m.astype(bool) & ref.known
        comps.append({"cx": float(cen[i][0]), "cy": float(cen[i][1]), "area": a, "r": float(np.sqrt(a / np.pi)),
                      "lit_around": float(lit[annulus].mean()) if annulus.any() else None})
    if any(c.get("global") for c in comps):
        for tr in live: tr["unseen_after"] = t; tr.setdefault("global_events", []).append(t)
        continue
    # After birth a track is judged by the dark share of its own disc, not by
    # re-finding a component: a smoke's hatched texture keeps its component near
    # AREA_MIN, and re-detection split one smoke into three tracks.
    dkb = grey_dark
    for tr in live:
        disc = ((XX - tr["cx"]) ** 2 + (YY - tr["cy"]) ** 2 <= (0.7 * tr["r"]) ** 2) & ref.known
        seen = disc & ~occ
        if seen.sum() < 0.3 * max(1, disc.sum()):
            tr["unseen_after"] = t; tr["occluded"] = tr.get("occluded", 0) + 1   # covered, not gone
            continue
        frac = float(dkb[seen].mean())
        if frac >= 0.3:
            tr.update(last=t, miss=0, n=tr["n"] + 1); tr.pop("unseen_after", None)
        else:
            tr["miss"] += 1
    used = set()
    for j, c in enumerate(comps):
        if any(np.hypot(c["cx"] - tr["cx"], c["cy"] - tr["cy"]) <= max(8.0, tr["r"]) for tr in live):
            used.add(j)
            tr = min(live, key=lambda tr: np.hypot(c["cx"] - tr["cx"], c["cy"] - tr["cy"]))
            tr["areas"].append(c["area"]); tr["lit"].append(c["lit_around"])
    for tr in [tr for tr in live if tr["miss"] >= GONE]:
        live.remove(tr)
        close(tr, "censored:unobserved_before_absence" if tr.get("unseen_after", 0) > tr["last"] else "observed")
    for j, c in enumerate(comps):
        if j in used: continue
        live.append({"round": rnd, "first": t, "last": t, "cx0": c["cx"], "cy0": c["cy"], "cx": c["cx"], "cy": c["cy"],
                     "r": c["r"], "n": 1, "miss": 0, "areas": [c["area"]], "lit": [c["lit_around"]]})
for tr in live: close(tr, "censored:round_window_end")
keep = [tr for tr in tracks if tr["last"] - tr["first"] >= 1.0]
print(f"samples {samples}; raw tracks {len(tracks)}; >=1 s: {len(keep)}")
for tr in sorted(keep, key=lambda t: t["first"]):
    lits = [v for v in tr["lit"] if v is not None]
    print(f"r{tr['round']:>2} {tr['first']:7.2f}-{tr['last']:7.2f} ({tr['last']-tr['first']:5.2f}s) at ({tr['cx0']:.0f},{tr['cy0']:.0f})->({tr['cx']:.0f},{tr['cy']:.0f}) "
          f"area med {int(np.median(tr['areas']))} lit-around {max(lits) if lits else float('nan'):.2f} occluded {tr.get('occluded', 0)} end {tr['end']}")
json.dump([{k: v for k, v in tr.items()} for tr in keep], open(SP / "rounds_tracks.json", "w"), default=float)
