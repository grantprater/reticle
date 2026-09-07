r"""READ the observable area off the widget, instead of reconstructing it.

    .\.venv\Scripts\python.exe prototypes\cone_lit.py 612 300 1200

**Recorded 2026-09-06, and it is a correction to how this was being built:**
asked why the cone channel was refusing 13% of its area, and whether we cannot
simply tell where the vision cone is, given a pixel-perfect reference. The
answer is that we can, and that the 13% was the wrong thing to be worrying
about entirely.

THE REFERENCE WAS WRONG, AND IT WAS ALREADY IN THE STORE
----------------------------------------------------------
Every earlier attempt at reading the drawn cone differenced the frame against
`static` -- the per-pixel MEDIAN -- and then thresholded that globally
(`lift > base + 2*dev`). Two things wrong with it, and the second is the one
that matters:

* a global threshold on this widget is the mistake `CLAUDE.md` opens with. It
  eventually measures the world instead of the widget, and here it measured
  WALL OUTLINES: `floor_mask` dilates by 9 px so "floor" covers the white
  line-work, and those lines shift by a pixel between frames. The first render
  of this was a picture of the map's perimeter;
* **`two_state_gray` already stores the right reference and nothing used it.**
  `lo_gray` and `hi_gray` are the unlit and lit values PER PIXEL, with their
  within-state noise in `sd_lo`/`sd_hi`. On FLOOR they are separated by **53.9
  grey levels, 28.3 sigma** -- so "is this pixel lit" is a two-state decision
  against that pixel's own two values, with no global threshold anywhere.

Using it, on the UNDILATED classification (`labels == FLOOR | PLANT`) rather
than the dilated mask, the wall tracing disappears and the lit region comes out
as clean wedges. Two further things are subtracted rather than detected: the
AUDIO RING, a drawn annotation at a measured 94-95 px around the player, and
components under 150 px, because a cone is a large connected region and the
residue is speckle -- coverage rather than level, one dimension up.

WHAT IT SAYS ABOUT THE RECONSTRUCTION, WHICH IS THE POINT
-----------------------------------------------------------
Scoring the reconstructed area (fit a bearing per icon, raycast, union) against
the area the game itself draws:

    frame     reconstruction    precision    recall
    612 s          35.5%           28%        68%
    300 s          24.1%           33%        77%
    1200 s         18.2%           31%        79%

**Recall is good and precision is not.** The reconstruction finds most of what
the game lights, and then claims roughly three times as much. That is the
OVER-claiming direction -- the one that silently discards real enemy
observations -- and it dwarfs the 13% of area the ambiguity gate gives back.
The gate was never the problem.

THE OPEN QUESTION, AND IT IS A REAL ONE
-----------------------------------------
The drawn light FADES WITH DISTANCE. Measured over 407 cones, the share of the
reconstruction that is lit falls smoothly from 51% at 0-20 px to 13% at 100 px
with no cliff, so there is no hard range to read off. Two readings and they
are not the same:

* the cone genuinely ends, and an unbounded raycast is wrong;
* the cone reaches as far as the raycast says and the game renders it with a
  brightness gradient, so "lit" understates "visible" at distance.

**Do not pick one without measuring it.** If it is a gradient then the drawn
mask is a conservative floor on the observable area rather than its outline,
and using it as ground truth would under-claim in the far field exactly as the
raycast over-claims. The cheapest way to settle it is to ask the recorder,
who can see the cone in-game.

ONE THING THE LIGHT CANNOT DO
-------------------------------
It is the UNION of five players' cones, so it gives the collective observable
area directly -- which is what every SS11 invariant is written in terms of --
but it cannot say WHICH teammate sees a pixel. Attribution still needs
per-icon bearings. Reading the light and fitting bearings are answers to two
different questions, and the aggregate is the one that was blocked.
"""
import json, pathlib, sys
import cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from reticle.profiles import PROFILES
from reticle import minimap as M
from reticle import cone as C

SID = "a06f04a0059f"
OUT = pathlib.Path.cwd()
man = json.load(open(next((pathlib.Path.home()/"reticle-store"/"manifests").rglob(f"*{SID}*.json"))))
src = man["source"]; prof = PROFILES[man["source_profile"]]
box = M.minimap_roi_px(prof, int(src["width"]), int(src["height"]))
z = np.load(pathlib.Path.home()/"reticle-store"/"geometry"/f"{SID}.npz")
lab = z["labels"]
lo, hi = z["lo_gray"].astype(np.float64), z["hi_gray"].astype(np.float64)
sl = np.maximum(z["sd_lo"].astype(np.float64), 0.5)
sh = np.maximum(z["sd_hi"].astype(np.float64), 0.5)
floor = M.floor_mask(z["static"]); passable = floor | (lab == M.BOXEDGE)
sg64 = cv2.cvtColor(z["static"], cv2.COLOR_BGR2GRAY).astype(np.float64)

FLOOR_ONLY = lab == M.FLOOR
solid = FLOOR_ONLY | (lab == M.PLANT)
# A pixel can only be classified where the two states are actually separated.
sep = (hi - lo) / np.minimum(sl, sh)
usable = solid & (sep > 4.0) & (hi - lo > 6.0)
print(f"FLOOR only: hi-lo median {np.median((hi-lo)[FLOOR_ONLY]):.1f} grey levels, "
      f"{np.median(sep[FLOOR_ONLY]):.1f} sigma")
print(f"PLANT:      hi-lo median {np.median((hi-lo)[lab==M.PLANT]):.1f}")
print(f"usable pixels: {usable.sum()} ({usable.mean()*100:.1f}% of the widget, "
      f"{usable.sum()/solid.sum()*100:.0f}% of solid floor)\n")

fps = float(src["fps"])
cap = cv2.VideoCapture(src["path"])
tiles = []
for tsec in [float(a) for a in sys.argv[1:]]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(tsec * fps)))
    ok, fr = cap.read()
    if not ok:
        continue
    crop = fr[box[1]:box[3], box[0]:box[2]]
    if not M.widget_drawn(crop, sg64, floor):
        print(f"{tsec}: widget not drawn")
        continue
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)
    # nearest state in NOISE UNITS -- no global threshold anywhere
    zl = np.abs(g - lo) / sl
    zh = np.abs(g - hi) / sh
    lit = usable & (zh < zl)
    # SPATIAL COHERENCE. The per-pixel decision has none, and a cone is a large
    # connected region while the residue is speckle -- so open once and drop
    # small components. This is the same argument as requiring COVERAGE rather
    # than a level, one dimension up.
    lit = cv2.morphologyEx(lit.astype(np.uint8), cv2.MORPH_OPEN,
                           np.ones((3, 3), np.uint8)).astype(bool)
    n_c, lbl_c, st_c, _cen = cv2.connectedComponentsWithStats(lit.astype(np.uint8), 8)
    keep = np.zeros(n_c, bool)
    for ci in range(1, n_c):
        keep[ci] = st_c[ci, 4] >= 150
    lit = keep[lbl_c]

    allies = M.ally_icons(crop, floor, require_facing=False)
    selves = sorted(M.self_icons(crop, floor, require_facing=False),
                    key=lambda d: -d["cov"])[:1]
    if selves:
        YY, XX = np.mgrid[0:floor.shape[0], 0:floor.shape[1]]
        rad = np.hypot(XX - selves[0]["cx"], YY - selves[0]["cy"])
        lit &= ~((rad > 85) & (rad < 108))
    ic = [(d["cx"], d["cy"], d["facing"]) for d in allies + selves
          if d["facing"] is not None]
    agg, _ = C.observable(passable, ic, visible=floor)
    agg &= usable

    vis = np.zeros((*floor.shape, 3), np.uint8)
    vis[solid] = (50, 50, 50)
    vis[usable] = (70, 70, 70)
    vis[lit] = (60, 200, 255)
    vis[agg & ~lit] = (200, 80, 80)
    vis[agg & lit] = (90, 240, 140)
    for d in allies:
        cv2.circle(vis, (int(d["cx"]), int(d["cy"])), 10, (255, 255, 255), 1)
    for d in selves:
        cv2.circle(vis, (int(d["cx"]), int(d["cy"])), 12, (255, 0, 255), 1)
    inter = float((agg & lit).sum())
    print(f"{tsec:7.1f}s  LIT {lit.sum()/usable.sum()*100:5.1f}% of usable   "
          f"reconstruction {agg.sum()/usable.sum()*100:5.1f}%   "
          f"precision {inter/max(agg.sum(),1)*100:4.0f}%  "
          f"recall {inter/max(lit.sum(),1)*100:4.0f}%")
    cv2.putText(vis, f"{tsec:.0f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    tiles.append(vis)
cap.release()
if tiles:
    cv2.imwrite(str(OUT / "twostate.png"), np.hstack(tiles))
    print("\namber = lit only, blue = reconstruction only, green = both")
