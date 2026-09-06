r"""Fit the official map art to the in-game minimap widget, and score it.

    .\.venv\Scripts\python.exe prototypes\wiki_map.py fetch ascent lotus
    .\.venv\Scripts\python.exe prototypes\wiki_map.py fit <session> --map ascent
    .\.venv\Scripts\python.exe prototypes\wiki_map.py fit <session> --map ascent --against painted

the player, 2026-09-05: *the valorant wiki had minimap images, probably better than
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
he can look at a picture. Ask, do not derive; the search stays here as the
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

    best = fit(alpha, target)
    if a.fine:
        v, rot, s, _dx, _dy = best
        best = fit(alpha, target,
                   rots=np.arange(rot - 4, rot + 4.1, 1.0),
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
