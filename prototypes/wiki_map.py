r"""Fit the official map art to the in-game minimap widget, and score it.

    .\.venv\Scripts\python.exe prototypes\wiki_map.py fetch ascent lotus
    .\.venv\Scripts\python.exe prototypes\wiki_map.py fit <session> --map ascent
    .\.venv\Scripts\python.exe prototypes\wiki_map.py fit <session> --map ascent --against painted

Recorded 2026-09-05: : *the valorant wiki had minimap images, probably better than
our derived ones.* They are, and the reason is not resolution -- it is that the
derived static map is being asked to do two jobs and can only do one.

What the art is
---------------
`https://valorant.fandom.com/wiki/Maps`, the "Minimap" column; the files are
named `<Map> minimap.png` and come through the MediaWiki API. They are 1024 or
2048 px square RGBA PNGs of **the same asset the game draws in the widget** --
the same grey slab, the same white line-work, the same olive bomb sites -- and
they are tiny (15 kB for Ascent) because they are mostly flat colour.

**The alpha channel is an exact floor mask.** That is the whole point. The
shipped `floor_mask` is `sat < 60 & val > 110` then a 9 px dilation: a
threshold that got the bomb sites 93% wrong until the classifier was rewritten
round them, that grew a third "bomb site" out of 10921 px of brown void on
Split, and that still catches the agent HUD in the corner. The art states the
footprint instead of inferring it, and the bomb sites are their own colour.

The transform, measured
-----------------------
A plain similarity transform -- rotation, uniform scale, translation -- and
**the rotation is a per-map constant, not a global one**:

    map      IoU vs the painting   rot    scale    derived rule scores
    Ascent            92.7%           270.0   0.2252          91.3%
    Lotus             93.7%             0.0   0.4481          92.8%

    reproduce with:  wiki_map.py fit a06f04a0059f --map ascent  --against painted --fine
                     wiki_map.py fit 5822b6646448 --map lotus   --against painted --fine

Both rotations came back on a full 0-360 search in 5 degree steps and both
landed on an EXACT multiple of 90, which is what says this is a property of the
game's fixed/always_same orientation rather than three parameters fitted to
noise. Scale differs because the wiki files differ (2048 px for Ascent, 1024
for Lotus), not because the maps do.

**The rotation is per-map and the player can just read it off**, which is far
cheaper than the search that found it -- the derivation is minutes per map, and
the player can look at a picture. Ask, do not derive; the search stays here as the
check on the answer rather than the source of it.

It beats the derived rule on both maps, by 1.4 and 0.9 points. Do not oversell
that: a point either way on IoU is not the argument, and an earlier draft of
this docstring quoted a coarse-search figure that made it look like a wash.
The case for it is everything the derived rule cannot do at all:

* **it carries LABELS the derived rule cannot produce at all** -- bomb sites as
  their own colour, holes as alpha-zero, exactly, with no hue fitting;
* **it is PER-MAP, not per-session.** The derived median bakes in whatever was
  parked on the widget: a 2271 px blob of the vision cone on
  `c0b63335e635` is classified `box edge` where the full match says `floor`.
  Fit once per map, use on every session of it;
* **it needs no painting.** the player has painted two maps. There are eighteen;
* **it is exact where the derived rule is a threshold.**

So: **art for geometry, capture median for photometry.** The median is still
required -- `widget_drawn`'s correlation, the two-state interval residual and
every ability diff need to know what THESE pixels look like with nothing on
them, and no external render can say that. The two stop being one array.

What the art encodes, and the two hopes for it
--------------------------------------------------
on why the player raised it: *what I'm hoping this fixes the tiny holes in the
map firing off misreads, and makes the boxes easier to identify.* Measured:

**The alpha channel is exactly binary.** 0.0% of Ascent's and Split's pixels
carry a partial alpha, 0.5% of Lotus's. So the footprint is STATED, not
inferred, and there is no threshold anywhere in it.

**The greys are quantised, and the levels are structure.** Ascent's opaque
pixels, by value:

    118  69.0%   the base floor
    255   6.2%   the white line-work
    139   3.9%       145   2.8%    |  raised platforms, ramps, and BOXES -- rendered on the
    133   1.7%    |  map as small discrete rectangles at exactly the places
    136   0.9%    |  a box stands
    122   1.2%   /
    221   0.6%
    everything else < 0.4% each, and it is antialiasing

plus `BGR (118,152,152)` at 6.0%, the olive of the bomb sites, which is the
only non-grey. **So boxes and elevation come free as a lookup**, where
`minimap_geometry`'s box/wall split is described in this file as "already known
to be poor" -- the second hope, answered.

**The first hope was RIGHT and my first check of it was aimed at the wrong
quantity.** I counted interior holes -- Ascent 8, Lotus 13, Split 10, mostly
large -- concluded "the cracks are not holes", and reported that as a
correction to the player. the player, immediately: *I'm not entirely sure that's accurate.
There were misreads of non-minimap content as icons.*

That is the mechanism, and it makes the hole COUNT beside the point. A hole or
crack is a place where the widget is TRANSPARENT, so what shows through it is
the live world -- moving, high-contrast, and exactly the thing a blob detector
fires on. This directory's own opening line says it: *the widget is
semi-transparent over the void, and every content-based approach that ignored
it drowned in the world moving behind it.* A crack is a small piece of void
INSIDE the map, and the detections it produces are world content wearing an
icon's shape.

So the question is not how many holes there are, it is whether the searchable
mask admits them -- and the derived one does, because `floor_mask` grows by
9 px and that closes every crack narrower than that. Whether the count is 8 or
800 does not change it.

The art does not dilate, so a candidate sitting in a crack is refusable exactly
rather than by a margin.

**Do not read that as "floor_mask is 40% wrong".** It is 51.5% of the widget
against the art's 30.6%, but those two masks have different jobs and the
comparison is not like for like: the dilation is deliberate and load-bearing
for ring detection. The mask that IS comparable is the ability channel's
`searchable`, and there the painting is 29.8% against the art's 30.6% --
agreeing at 92.7% IoU. **The art is a drop-in for the searchable rule; it is
not a replacement for `floor_mask`, and swapping it in there would cost enemy
recall at the slab edge.**

Fitting a map with no painting
-------------------------------
Sixteen maps have no painted ground truth, so the fit there aligns the art's
alpha against the session's own derived `floor_mask`. That is good enough to
place three parameters -- the optimum is sharp -- while being too crude to BE
the labels, which is the division of labour this whole finding rests on.
Measured on Ascent that fit reaches IoU 0.748 against the derived mask, and the
residual is almost entirely `floor_mask`'s own false positives (the agent HUD
at the widget's edge), not art error.

Two traps this hit while being written, both recurrences
---------------------------------------------------------
* **a search that terminates at its own bound is not a result.** Lotus first
  came back at IoU 34.7% with the scale pinned to the top of the range, because
  the range was written for Ascent's 2048 px art and Lotus ships at 1024. The
  number looked like a falsification and was a bug in the harness;
* **binary masks are 0/1 or 0/255, never both.** An `alpha > 40` cast to uint8
  and then thresholded at 127 is empty, and the fit reported IoU 0.000 with
  every appearance of having run.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.minimap import floor_mask                            # noqa: E402

STORE = Path.home() / "reticle-store"
ART = STORE / "reference" / "maps"
API = "https://valorant.fandom.com/api.php"

#: Alpha above which the art counts as map. The channel is near-binary -- 25
#: distinct values over the whole image, almost all 0 or 255 -- so this is a
#: formality rather than a tuned edge.
ALPHA_MIN = 40

#: How far the wiki's art is rotated from what the game draws, per map.
#:
#: **READ OFF THE MAPS DIRECTLY, 2026-09-05 -- not fitted.** The search
#: in `fit()` recovers 270 for Ascent and 0 for Lotus unprompted, which is what
#: makes this table checkable, but it is minutes per map to derive and seconds
#: for the player to look at. Ask, do not derive.
#:
#: The reading of the split, which is the part no measurement would have given:
#: *all of the maps either kept the rotation the same or did the same rotation
#: as ascent ... seems like basically based on the geometry of the maps.* So
#: there are exactly TWO values and the choice follows the map's shape -- a
#: long map is turned to fit the square widget. That is why a third value has
#: never appeared and probably will not.
ROTATION = {
    "bind": 0.0, "breeze": 0.0, "fracture": 0.0, "pearl": 0.0,
    "lotus": 0.0, "sunset": 0.0,
    "haven": 270.0, "split": 270.0, "ascent": 270.0,
    "icebox": 270.0, "abyss": 270.0, "corrode": 270.0,
}


def fetch(names: list[str]) -> None:
    """Download `<Map> minimap.png` for each named map into the store."""
    titles = "|".join(f"File:{n.capitalize()} minimap.png" for n in names)
    url = (f"{API}?action=query&titles={urllib.parse.quote(titles, safe='|')}"
           f"&prop=imageinfo&iiprop=url|size&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": "reticle/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    ART.mkdir(parents=True, exist_ok=True)
    for _pid, page in data["query"]["pages"].items():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            print(f"  MISSING  {page['title']}")
            continue
        name = page["title"].split(":", 1)[1].split(" ")[0].lower()
        out = ART / f"{name}.png"
        ireq = urllib.request.Request(info["url"],
                                      headers={"User-Agent": "reticle/1.0"})
        with urllib.request.urlopen(ireq, timeout=120) as im:
            out.write_bytes(im.read())
        print(f"  {name:10s} {info['width']}x{info['height']}  -> {out}")


def art_alpha(map_name: str) -> np.ndarray:
    """The art's footprint, cropped to its own bounding box, as 0/255."""
    p = ART / f"{map_name}.png"
    if not p.is_file():
        raise SystemExit(f"no art for {map_name} -- run: wiki_map.py fetch {map_name}")
    im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if im is None or im.shape[2] < 4:
        raise SystemExit(f"{p} has no alpha channel")
    a = ((im[:, :, 3] > ALPHA_MIN).astype(np.uint8)) * 255
    ys, xs = np.where(a > 127)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _warp(alpha: np.ndarray, rot: float, scale: float) -> np.ndarray:
    h0, w0 = alpha.shape
    M = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, scale)
    side = int(max(h0, w0) * scale * 1.6)
    M[0, 2] += side / 2 - w0 / 2
    M[1, 2] += side / 2 - h0 / 2
    return cv2.warpAffine(alpha, M, (side, side), flags=cv2.INTER_AREA) > 127


def _place(r: np.ndarray, target: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(target)
    side = r.shape[0]
    h, w = target.shape
    y0, x0 = max(0, dy), max(0, dx)
    y1, x1 = min(h, dy + side), min(w, dx + side)
    if y1 <= y0 or x1 <= x0:
        return out
    out[y0:y1, x0:x1] = r[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


def fit(alpha: np.ndarray, target: np.ndarray, rots=range(0, 360, 5),
        scales=None):
    """Best (IoU, rot, scale, dx, dy) placing `alpha` onto `target`.

    Scale is bounded by the AREA RATIO rather than by a written-in range --
    the first version of this used a fixed range tuned on Ascent's 2048 px art
    and silently pinned Lotus's 1024 px art to the bound, reporting a
    falsification that was a harness bug. A search that terminates at its own
    limit is not a result, so the limits are derived from the data.
    """
    a_area = (alpha > 127).sum()
    t_area = target.sum()
    s0 = float(np.sqrt(t_area / a_area))
    if scales is None:
        scales = np.arange(s0 * 0.75, s0 * 1.30, s0 * 0.018)
    tM = cv2.moments(target.astype(np.uint8), binaryImage=True)
    tcx, tcy = tM["m10"] / tM["m00"], tM["m01"] / tM["m00"]
    best = None
    for rot in rots:
        for s in scales:
            r = _warp(alpha, rot, s)
            M = cv2.moments(r.astype(np.uint8), binaryImage=True)
            if M["m00"] == 0:
                continue
            bx = int(tcx - M["m10"] / M["m00"])
            by = int(tcy - M["m01"] / M["m00"])
            for ddy in range(-8, 9, 2):
                for ddx in range(-8, 9, 2):
                    c = _place(r, target, bx + ddx, by + ddy)
                    u = (c | target).sum()
                    v = (c & target).sum() / u if u else 0.0
                    if best is None or v > best[0]:
                        best = (v, float(rot), float(s), bx + ddx, by + ddy)
    return best


def art_grey(map_name: str):
    """The art's grey render and its footprint, cropped together.

    The SILHOUETTE is enough to place the transform roughly and not enough to
    place it well: fitted against a session's derived floor mask -- which on
    Ascent carries the agent HUD at the widget's edge -- the outline-only fit
    lands 7 points worse against the painting than the same art fitted
    against the painting itself (85.7% against 92.7%). An outline can slide
    along its own edge; the line-work inside cannot.
    """
    im = cv2.imread(str(ART / f"{map_name}.png"), cv2.IMREAD_UNCHANGED)
    a = im[:, :, 3] > ALPHA_MIN
    g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    g[~a] = 0
    ys, xs = np.where(a)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    return g[sl], a[sl]


def refine_ncc(map_name, med_gray, rot, scale, dx, dy, span=10):
    """Lock the fit onto the STRUCTURE by correlating art grey against the median.

    Seeded from the silhouette fit and searched locally. This is what makes the
    art usable without a painting to fit against: measured on the two
    paintings, silhouette-only scores 85.7% / 93.5% and the same fit refined
    here scores **92.3% / 94.0%** -- recovering painting-quality alignment from
    the session's own median, which every session has.

    Correlation, not difference: the art is a flat render and the widget is that
    render composited over live scenery at some brightness, so the two agree in
    STRUCTURE and not in level. Same reason `widget_drawn` correlates.
    """
    ag, aa = art_grey(map_name)
    H, W = med_gray.shape
    best = None
    for s in np.arange(scale * 0.94, scale * 1.06, scale * 0.004):
        h0, w0 = ag.shape
        M = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, s)
        side = int(max(h0, w0) * s * 1.6)
        M[0, 2] += side / 2 - w0 / 2
        M[1, 2] += side / 2 - h0 / 2
        rg = cv2.warpAffine(ag, M, (side, side), flags=cv2.INTER_AREA)
        ra = cv2.warpAffine(aa.astype(np.uint8) * 255, M, (side, side),
                            flags=cv2.INTER_AREA) > 127
        for ddy in range(dy - span, dy + span + 1, 2):
            for ddx in range(dx - span, dx + span + 1, 2):
                c = np.zeros_like(med_gray)
                cm = np.zeros(med_gray.shape, bool)
                y0, x0 = max(0, ddy), max(0, ddx)
                y1, x1 = min(H, ddy + side), min(W, ddx + side)
                if y1 <= y0 or x1 <= x0:
                    continue
                c[y0:y1, x0:x1] = rg[y0 - ddy:y1 - ddy, x0 - ddx:x1 - ddx]
                cm[y0:y1, x0:x1] = ra[y0 - ddy:y1 - ddy, x0 - ddx:x1 - ddx]
                if cm.sum() < 5000:
                    continue
                a1 = c[cm] - c[cm].mean()
                b1 = med_gray[cm] - med_gray[cm].mean()
                den = float(np.sqrt((a1 * a1).sum() * (b1 * b1).sum()))
                if den <= 0:
                    continue
                ncc = float((a1 * b1).sum() / den)
                if best is None or ncc > best[0]:
                    best = (ncc, float(s), int(ddx), int(ddy))
    return best


def map_of(sid: str) -> str | None:
    """The session's map, from its manifest tags. Already recorded at ingest."""
    m = STORE / "manifests" / f"{sid}.json"
    if not m.is_file():
        return None
    tags = json.loads(m.read_text(encoding="utf-8")).get("tags", [])
    return next((t.split(":", 1)[1] for t in tags if t.startswith("map:")), None)


def fit_for_session(sid: str, map_name: str | None = None):
    """The art's footprint in this session's widget pixels, or None.

    **Cached per session**, because the fit is a search and the answer is a
    constant: three numbers that depend on the map and the widget geometry,
    neither of which moves within a session. Without the cache this would be
    minutes on every call, which is how a good mask becomes a mask nobody uses.

    Returns None -- never raises -- when the map is unknown, the art is not
    fetched, or the session has no geometry to fit against. Callers keep their
    existing fallback; this is an upgrade path, not a dependency.
    """
    map_name = map_name or map_of(sid)
    if not map_name:
        return None
    cache = STORE / "reference" / "fits" / f"{sid}.npz"
    if cache.is_file():
        z = np.load(cache)
        return _place(_warp(art_alpha(map_name), float(z["rot"]), float(z["scale"])),
                      np.zeros(tuple(z["shape"]), bool), int(z["dx"]), int(z["dy"]))
    try:
        alpha = art_alpha(map_name)
    except SystemExit:
        return None
    g = STORE / "geometry" / f"{sid}.npz"
    if not g.is_file():
        return None
    z = np.load(g)
    m = cv2.erode(floor_mask(z["static"]).astype(np.uint8),
                  np.ones((9, 9), np.uint8)) > 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    target = lab == (1 + int(np.argmax(st[1:, 4]))) if n > 1 else m
    known = ROTATION.get(map_name)
    rots = [known] if known is not None else range(0, 360, 5)
    best = fit(alpha, target, rots=rots)
    if best is None:
        return None
    v, rot, sc, dx, dy = best
    # Silhouette to get close, STRUCTURE to lock it in -- see `refine_ncc`.
    med_gray = cv2.cvtColor(z["static"], cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref = refine_ncc(map_name, med_gray, rot, sc, dx, dy)
    if ref is not None:
        ncc, sc, dx, dy = ref
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, rot=rot, scale=sc, dx=dx, dy=dy, iou=v,
             ncc=(ref[0] if ref else 0.0), shape=np.array(target.shape))
    return _place(_warp(alpha, rot, sc), target, dx, dy)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("maps", nargs="+")
    g = sub.add_parser("fit")
    g.add_argument("session")
    g.add_argument("--map", required=True)
    g.add_argument("--against", choices=("derived", "painted"), default="derived",
                   help="derived floor_mask (any session) or the painting")
    g.add_argument("--fine", action="store_true",
                   help="1-degree rotation search around the coarse answer")
    g.add_argument("--dump", default=None)
    g.add_argument("--search-rot", action="store_true",
                   help="re-derive the rotation instead of using the table")
    a = ap.parse_args(argv)

    if a.cmd == "fetch":
        fetch(a.maps)
        return 0

    alpha = art_alpha(a.map)
    if a.against == "painted":
        p = STORE / "labels" / "map_mask" / f"{a.session}.png"
        if not p.is_file():
            raise SystemExit(f"no painted mask for {a.session}")
        target = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) > 127
        what = "the painting"
    else:
        z = np.load(STORE / "geometry" / f"{a.session}.npz")
        m = cv2.erode(floor_mask(z["static"]).astype(np.uint8),
                      np.ones((9, 9), np.uint8)) > 0
        # `floor_mask` also catches the widget rim and the corner HUD; the map
        # is the largest component and that is all this needs to align to.
        n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
        target = lab == (1 + int(np.argmax(st[1:, 4]))) if n > 1 else m
        what = "the derived floor_mask"

    # With the rotation known the fit has TWO free parameters, not three, and
    # the search becomes a check rather than a derivation.
    known = ROTATION.get(a.map)
    rots = [known] if (known is not None and not a.search_rot) else range(0, 360, 5)
    if known is not None and not a.search_rot:
        print(f"  rotation {known:.0f} deg from the table (--search-rot to re-derive)")
    best = fit(alpha, target, rots=rots)
    if a.fine:
        v, rot, s, _dx, _dy = best
        fine_rots = ([rot] if (known is not None and not a.search_rot)
                     else np.arange(rot - 4, rot + 4.1, 1.0))
        best = fit(alpha, target, rots=fine_rots,
                   scales=np.arange(s * 0.94, s * 1.06, s * 0.006))
    v, rot, s, dx, dy = best
    print(f"{a.map} art vs {what} ({a.session})")
    print(f"  IoU {v * 100:.1f}%   rot {rot:.1f} deg   scale {s:.4f}   "
          f"offset ({dx},{dy})")
    if abs(rot % 90) > 2 and abs(rot % 90 - 90) > 2:
        print("  ! rotation is not a multiple of 90 -- suspect the fit")

    if a.dump:
        c = _place(_warp(alpha, rot, s), target, dx, dy)
        vis = np.zeros(target.shape + (3,), np.uint8)
        vis[..., 1] = target * 200          # green: what we had
        vis[..., 2] = c * 200               # red: the art
        cv2.imwrite(a.dump, cv2.resize(vis, None, fx=1.3, fy=1.3,
                                       interpolation=cv2.INTER_NEAREST))
        print(f"  overlay -> {a.dump}   (yellow = agree)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
