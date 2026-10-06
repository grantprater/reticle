r"""Why minimap geometry is drawn from the GAME'S OWN FILES, and the fit of each profile's transform.

    .\.venv\Scripts\python.exe prototypes\minimap_geometry.py --fit <dir of training-key capture npz>
    .\.venv\Scripts\python.exe prototypes\minimap_geometry.py --maps
    .\.venv\Scripts\python.exe prototypes\minimap_geometry.py <map>__<profile> --sheet out.png

`reticle/map_asset.py` draws the geometry and `reticle geometry --all` caches
it, then `prototypes/line_classes.py bake --all` and `reticle occluders --all`
add the arrays read off the static. This file holds the argument and refits
the per-profile constants into `reticle/frozen/geometry_profiles.json`.

What it reads
-------------
The minimap textures VALORANT draws, exported by the store's extractor
(`<store>/tools/game-extract`, CUE4Parse) into
`<store>/reference/game-files/<BUILD>/minimap-geometry/`, whose
`manifest.jsonl` names each texture's game path and sha256:

* `TX_Map_<code>_FogOfWar` -- the map as the widget draws it UNLIT. Each map's
  `<code>_UIData` names it as its `DisplayIcon` (Ascent names
  `..._FogOfWar_Update`, byte-identical to `..._FogOfWar`: the extractor
  deduplicated them by sha256). The valorant-api display icon and the wiki art
  are this texture: on opaque texels their grey differs from it by at most
  [metric:official_geometry/assets#api_vs_fog_mad_max=0.34] levels and from
  the revealed texture by at least
  [metric:official_geometry/assets#api_vs_revealed_mad_min=58.07], on all
  seven fetched maps (`prototypes/official_geometry_eval.py`);
* `TX_Map_<code>_Revealed` -- the same plan LIT, where an ally can see. Its
  floor is 181 against the fog texture's 118.

So the two resting states `lo_gray` and `hi_gray` describe are two textures,
and nothing here needs a capture to say what a map looks like.

Why the old builder took a capture, and why that was wrong
---------------------------------------------------------
Until 2026-10-05 this file took `static`, `lo_gray`, `hi_gray` and the SD maps
from a per-pixel median of 180 frames of the longest recording on the key, on
the stated ground that the widget is semi-transparent over live world, so no
external render could say what its pixels look like
(`docs/archive/BACKLOG-through-2026-09-23.md`; commit 058664c). The art grey
failed as a lighting FILL in `reticle/lighting.py` (2026-09-07) because the
fill asked a flat 118 to predict per-pixel lighting. Nobody compared the game's
textures with the capture median. Measured over the eleven keys a session
reads, the map layer is OPAQUE: on flat floor the capture median sits
[metric:official_geometry/all#flat_static_minus_fog_median=-1.0] grey level
from the fog texture, and on every key within
[metric:official_geometry/all#flat_static_minus_fog_max=-0.59] of it; the
void bleeds through only
where the texture's alpha is zero [domain:minimap/transparency].

Placement is a per-profile constant
-----------------------------------
`map_shade` held that the four-parameter placement needed a capture, because
the art's CROPPED centres sat 13 px apart. The uncropped texture's centre lands
on one widget point per profile: a free similarity fit on each of the eleven
keys moved it at most
[metric:official_geometry/all#centre_dev_max_px=0.127] px from the fitted
point and the scale at most
[metric:official_geometry/all#scale_dev_max_pct=0.139]%.
That point is the drawn ring's centre [domain:minimap/widget-ring]. Rotation
is the per-map table `map_asset.ROTATION`, read off by the player; a capture may
still turn the widget [domain:minimap/side-based-widget-turns-between-rounds],
which `reticle/widget_frame.py` measures against this frame.

What is fitted, and on what
---------------------------
Eight things are not in the game files. Each was fitted ONLY on the four
training keys, Ascent and Lotus at both profiles (`fit`, from their capture
geometry), and is frozen in `reticle/frozen/geometry_profiles.json`:

* the placement (scale and texture-centre point) per profile;
* the render target the widget samples through, `RT_SIDE`: the texture is
  resampled bilinearly to 768 px, then bilinearly into the widget. Of seven
  filters tried it reproduced the capture's white line-work best on the
  training keys;
* a per-channel gain and offset of the opaque map;
* the void: the live world, which no file holds. It is a per-profile colour
  darkened by a blurred copy of the map's alpha, and darker again inside holes
  the map encloses. It is a background for differencing, not map; every reader
  searches inside the opaque slab;
* the ring: a thin circle at the texture centre, its radius and its lift;
* the clip: at the largest map scaling the map is painted only inside the ring
  [domain:capture/largest-scaling-shows-whole-map-belief];
* `sd_lo` and `sd_hi` per pixel class (flat map, map structure, map edge,
  void): the capture's own noise, which only a capture holds;
* `lo_gray` and `hi_gray` in the void, offsets from the void colour.

A profile with no entry (`valorant-16x9-crop75`, whose only capture was
removed) keeps its capture geometry, read only.

Where it puts the world
-----------------------
Riot's records place every player in game units, and `MapFrame` carries them
into widget px through `shade_fit`. Paired by victim over 22 matches, the
official transform changed the mean position error by
[metric:official_geometry/riot_world/valorant-16x9#mean_change=-0.137] px on
the 331 px widget and by
[metric:official_geometry/riot_world/valorant-16x9-bigmap#mean_change=0.148]
px on the 465 px one, whose session-bootstrap interval reaches
[metric:official_geometry/riot_world/valorant-16x9-bigmap#mean_change_lo=-0.016].
The error left is a per-map offset of one to two texture px, alike at both
profiles and in every match of a map, so it lies between the world-to-texture
constants (valorant-api's equal the game's UIData) and the texture, not in the
placement. Nothing here fits it.

Labels and shade
----------------
`map_asset.art_classes` quantises the fog texture into terrain classes at
texture resolution and `shade_layers` warps them by AREA coverage through the
same placement; `classify_art` maps them to the geometry classes. `shade_fit`
keeps its old convention against the wiki art's crop, so `geometry.map_scale`,
`raised_edges.zoom` and the Riot `MapFrame` read it unchanged, except that its
offsets are now fractional and `MapFrame` reads them so; its IoU and NCC
slots hold 1.0, a placement that is the per-profile constant rather than a
fit. `map_affine` is the same placement as a 2x3 from texture px.

The occluder and line arrays derive from `static` and `labels`; rebuild them
after this with `line_classes.py bake` and `reticle occluders`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import geometry as G                                 # noqa: E402
from reticle import map_asset as A                                # noqa: E402
from reticle.minimap import (BORDER, BOXEDGE, FLOOR, HOLE,        # noqa: E402
                             PLANT, VOID)

STORE = Path.home() / "reticle-store"

COLOURS = {VOID: (40, 40, 40), FLOOR: (90, 90, 90), HOLE: (20, 20, 110),
           BORDER: (255, 255, 255), BOXEDGE: (60, 200, 255), PLANT: (40, 220, 220)}


def free_place(static: np.ndarray, map_name: str, seed: dict) -> np.ndarray:
    """(scale, centre x, centre y) that best lay the fog texture over a capture
    static, by NCC over the dilated map; a coarse grid first, because the
    similarity has false optima a few px off."""
    from scipy.optimize import minimize
    shape = static.shape[:2]
    g = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.float32)
    fog = A.premultiplied(A.read_bgra(A.textures(map_name, STORE)["fog"], STORE))
    rot = A.rotation(map_name)
    s0 = seed.get("scale", 0.45 if shape[0] > 400 else 0.286)
    c0 = seed.get("centre", (shape[1] / 2, shape[0] / 2 + 15))

    def neg(v):
        F = A.draw(fog, A.map_affine(rot, v[0], v[1:]), shape)
        a = F[..., 3]
        msk = cv2.dilate((a > 0.02).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        x = (F[..., :3].mean(2) + (1 - a) * 0.33)[msk]
        y = g[msk]
        x, y = x - x.mean(), y - y.mean()
        return -float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum()))
    grid = [(neg([sc, c0[0] + dx, c0[1] + dy]), sc, c0[0] + dx, c0[1] + dy)
            for sc in s0 * np.array([0.97, 0.985, 1.0, 1.015, 1.03])
            for dx in range(-14, 15, 2) for dy in range(-14, 15, 2)]
    _, s0, *c0 = min(grid)
    r = minimize(neg, [s0, *c0], method="Nelder-Mead",
                 options={"xatol": 1e-4, "fatol": 1e-7, "maxiter": 800,
                          "initial_simplex": [[s0, *c0], [s0 * 1.003, *c0],
                                              [s0, c0[0] + 0.5, c0[1]],
                                              [s0, c0[0], c0[1] + 0.5]]})
    return r.x


def fit(baked: Path) -> dict:
    """Refit every profile's transform from the training keys' capture geometry
    in `baked` (`<store>/geometry/`, read only). Run 2026-10-05; the result is
    `A.PROFILES_FILE`."""
    out = {}
    seeds = A.transforms()
    for profile in sorted({k.split("__")[1] for k in A.TRAIN_KEYS}):
        keys = [k for k in A.TRAIN_KEYS if k.endswith("__" + profile)]
        zs = {k: dict(np.load(baked / f"{k}.npz")) for k in keys}
        shape = zs[keys[0]]["static"].shape[:2]
        # 1. placement: free similarity fit of the fog texture per key
        place = [free_place(zs[k]["static"], k.split("__")[0], seeds.get(profile, {}))
                 for k in keys]
        scale, cx, cy = (float(v) for v in np.mean(place, 0))
        P = {"shape": list(shape), "scale": scale, "centre": [cx, cy], "frame": [1920, 1080]}
        # 2. ring radius and lift, from the void's radial profile
        radii, lifts = [], []
        yy, xx = np.mgrid[:shape[0], :shape[1]]
        rr = np.hypot(xx - cx, yy - cy)
        for k in keys:
            g = cv2.cvtColor(zs[k]["static"], cv2.COLOR_BGR2GRAY).astype(np.float32)
            vo = zs[k]["labels"] == VOID
            rs = np.arange(min(shape) * 0.3, min(shape) * 0.52, 0.25)
            med = [np.median(g[vo & (np.abs(rr - r0) < 0.5)])
                   if (vo & (np.abs(rr - r0) < 0.5)).sum() > 30 else 0 for r0 in rs]
            r0 = float(rs[int(np.argmax(med))])
            radii.append(r0)
            lifts.append(float(np.median(g[vo & (np.abs(rr - r0) < 0.5)])
                               - np.median(g[vo & (np.abs(np.abs(rr - r0) - 3) < 0.5)])))
        P["ring_r"], P["ring_lift"] = float(np.mean(radii)), float(np.mean(lifts))
        # 3. gain, void, sd and void offsets, on the drawn layers (unit gain)
        P["gain"] = [[1.0, 0.0]] * 3
        gains, rows = [], []
        sd = {"sd_lo": [[] for _ in range(4)], "sd_hi": [[] for _ in range(4)]}
        dlo, dhi = [], []
        for k in keys:
            fog, _rev, _M, _r, _t = A.drawn_layers(k.split("__")[0], profile, STORE, P)
            a = fog[..., 3]
            st = zs[k]["static"].astype(np.float32)
            g = cv2.cvtColor(zs[k]["static"], cv2.COLOR_BGR2GRAY).astype(np.float32)
            cls = A.pixel_classes(a, cv2.cvtColor(fog[..., :3] * 255.0, cv2.COLOR_BGR2GRAY))
            core = cls <= A.C_STRUCT
            gains.append([np.linalg.lstsq(np.vstack([fog[..., c][core] * 255,
                                                     np.ones(core.sum())]).T,
                                          st[..., c][core], rcond=None)[0].tolist()
                          for c in range(3)])
            away = np.abs(rr - P["ring_r"]) > 3
            rows.append((a, st, (cls == A.C_VOID) & (zs[k]["labels"] != FLOOR) & away))
            for nm in sd:
                for c in range(4):
                    sd[nm][c].append(float(np.median(zs[k][nm][cls == c])))
            dlo.append(float(np.median((zs[k]["lo_gray"] - g)[cls == A.C_VOID])))
            dhi.append(float(np.median((zs[k]["hi_gray"] - g)[cls == A.C_VOID])))
        best = None
        for sig in (8, 16, 24, 32, 48, 64):
            for kk in np.arange(0.0, 0.85, 0.05):
                for hole in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
                    err, cols = 0.0, []
                    for a, st, sel in rows:
                        f = 1 - kk * cv2.GaussianBlur(a, (0, 0), sig)
                        f = np.where(A.enclosed(a), f * hole, f)[sel]
                        col = [(f * st[..., c][sel]).sum() / (f * f).sum() for c in range(3)]
                        cols.append(col)
                        err += sum(np.abs(st[..., c][sel] - col[c] * f).mean() for c in range(3))
                    if best is None or err < best[0]:
                        best = (err, sig, float(kk), hole, np.mean(cols, 0).tolist())
        P.update(gain=np.mean(gains, 0).tolist(),
                 void={"sigma": best[1], "k": best[2], "hole": best[3], "colour": best[4]},
                 sd_lo=[float(np.mean(v)) for v in sd["sd_lo"]],
                 sd_hi=[float(np.mean(v)) for v in sd["sd_hi"]],
                 void_lo=float(np.mean(dlo)), void_hi=float(np.mean(dhi)),
                 placement_each={k: [round(float(v), 5) for v in p] for k, p in zip(keys, place)})
        out[profile] = P
    return out


def sheet(gkey: str, out: str) -> int:
    """The key's drawn static beside its labels, for looking at."""
    f = A.render(*G.parse(gkey), STORE)
    vis = np.zeros_like(f["static"])
    for k, c in COLOURS.items():
        vis[f["labels"] == k] = c
    cv2.imwrite(out, np.hstack([f["static"], vis]))
    print(f"  wrote {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fit and inspect geometry drawn from the game's textures.")
    ap.add_argument("key", nargs="?", help="a geometry key, `<map>__<profile>`, for --sheet")
    ap.add_argument("--maps", action="store_true", help="list the maps the texture set holds")
    ap.add_argument("--sheet", help="write the key's static and labels to this PNG")
    ap.add_argument("--fit", default=None, metavar="DIR",
                    help="refit every profile's transform from the training keys' capture npz in DIR")
    args = ap.parse_args(argv)
    if args.fit:
        got = fit(Path(args.fit))
        A.PROFILES_FILE.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {A.PROFILES_FILE}")
        return 0
    if args.maps:
        for name, (code, _fog) in sorted(A.maps(STORE).items()):
            try:
                t = A.textures(name, STORE)
                print(f"  {name:10s} {code:10s} {t['fog']['game_path'].rsplit('/', 1)[1]}  "
                      f"{t['rev']['game_path'].rsplit('/', 1)[1]}")
            except SystemExit as e:
                print(f"  {name:10s} {code:10s} REFUSED: {e}")
        return 0
    if args.key and args.sheet:
        return sheet(args.key, args.sheet)
    print("give --fit DIR, --maps, or a key with --sheet; build with `reticle geometry`")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
