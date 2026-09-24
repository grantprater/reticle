r"""Ungated minimap dark-region tracks over whole match rounds.

    .\.venv\Scripts\python.exe prototypes\entity_mining_rounds.py

The match check for `entity_mining_residual.py` (predictions R1-R4 under
`entity-mining-promotion`). A match has no tray cast for anyone else's smoke,
so births are ungated: every `lighting.raw_dark` component of at least 150 px,
matched frame to frame at 4 Hz, alive at least 1 s. Rounds 5, 10, 17 and 22 of
`a06f04a0059f`: the 5th and 10th of each half, which the player chose as
ult-likely.

Reviewed by eye, 2026-09-24: of 16 tracks, 5 are smokes, and three more are
one further smoke split by teammate icons crossing it. Every fully observed
smoke reads 18.0 s; none reads Dark Cover's 15 s [domain:abilities/omen-dark-cover].
The rest are enemy icons (dark portraits), one ally icon, and ally death marks
(the blue X persists to round end). No viewcone produced a track. Smokes
bordering lit floor still read dark.

Known defects, in the order they should be fixed: icons crossing a smoke end
its track (icon pixels must be unobserved there, not absent); icons and death
marks are tracked (gate against their owners, `adjudication.death` and the
ally icon reader, rather than tuning); a track whose widget vanishes has no
censored end here.
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
tracks, live, samples = [], [], 0
ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
for who, smp in decode.sample_windows(src["path"], float(src["fps"]), {"dark": (HZ, spans)}):
    t = smp.t_ms / 1000.0; samples += 1
    rnd = next(k for k in ROUNDS if rounds[k]["t_start_ms"] <= smp.t_ms <= rounds[k]["t_end_ms"] + 1)
    crop = smp.frame[y0:y1, x0:x1]
    if not minimap.widget_drawn(crop, sgray, floor):
        continue                                   # unobserved: no track ages
    dk = lighting.raw_dark(crop, ref).astype(np.uint8)
    for s in minimap.self_icons(crop, floor, require_facing=False):
        cv2.circle(dk, (int(s["cx"]), int(s["cy"])), int(s["r"]) + 6, 0, -1)
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
        for tr in live: tr.setdefault("global_events", []).append(t)
        continue
    used = set()
    for tr in live:
        best = min(((np.hypot(c["cx"] - tr["cx"], c["cy"] - tr["cy"]), j) for j, c in enumerate(comps) if j not in used), default=None)
        if best and best[0] <= max(8.0, 0.6 * tr["r"]):
            c = comps[best[1]]; used.add(best[1])
            tr.update(cx=c["cx"], cy=c["cy"], r=max(tr["r"], c["r"]), last=t, miss=0, n=tr["n"] + 1)
            tr["areas"].append(c["area"]); tr["lit"].append(c["lit_around"])
        else:
            tr["miss"] += 1
    for tr in [tr for tr in live if tr["miss"] >= GONE]:
        live.remove(tr); tracks.append(tr)
    for j, c in enumerate(comps):
        if j in used: continue
        live.append({"round": rnd, "first": t, "last": t, "cx0": c["cx"], "cy0": c["cy"], "cx": c["cx"], "cy": c["cy"],
                     "r": c["r"], "n": 1, "miss": 0, "areas": [c["area"]], "lit": [c["lit_around"]]})
tracks += live
keep = [tr for tr in tracks if tr["last"] - tr["first"] >= 1.0]
print(f"samples {samples}; raw tracks {len(tracks)}; >=1 s: {len(keep)}")
for tr in sorted(keep, key=lambda t: t["first"]):
    lits = [v for v in tr["lit"] if v is not None]
    print(f"r{tr['round']:>2} {tr['first']:7.2f}-{tr['last']:7.2f} ({tr['last']-tr['first']:5.2f}s) at ({tr['cx0']:.0f},{tr['cy0']:.0f})->({tr['cx']:.0f},{tr['cy']:.0f}) "
          f"area med {int(np.median(tr['areas']))} max lit-around {max(lits) if lits else None:.2f} n {tr['n']}")
json.dump([{k: v for k, v in tr.items()} for tr in keep], open(SP / "rounds_tracks.json", "w"), default=float)
