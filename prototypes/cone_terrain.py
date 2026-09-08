r"""Does the ART's terrain shade explain the always-lit pixels? YES, 3x.

    .\.venv\Scripts\python.exe prototypes\cone_terrain.py

The finding, and the argument for reading the widget as LAYERS, is in
`prototypes/CLAUDE.md` under "THE WIDGET IS LAYERS". The short version:

If the 'lit' classifier is really reading elevation, then pixels lit in nearly
every frame should sit at art greys OTHER than the main floor shade, and pixels
lit sometimes -- real cones -- should sit on the main floor.
"""
import json, pathlib, sys
import cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from reticle.profiles import PROFILES
from reticle import minimap as M
from reticle import geometry as _G                                  # noqa: E402
import wiki_map as WM

SID = "a06f04a0059f"
# In the STORE, not the CWD. Running this from the repo root dropped a 1.8 MB
# untracked npz beside the source, one `git add -A` away from being committed.
CACHE = pathlib.Path.home() / "reticle-store" / "analysis" / f"cone_terrain_{SID}.npz"
CACHE.parent.mkdir(parents=True, exist_ok=True)
man = json.load(open(next((pathlib.Path.home()/"reticle-store"/"manifests").rglob(f"*{SID}*.json"))))
src = man["source"]; prof = PROFILES[man["source_profile"]]
box = M.minimap_roi_px(prof, int(src["width"]), int(src["height"]))
z = np.load(_G.require(SID))
lab = z["labels"]
lo, hi = z["lo_gray"].astype(np.float64), z["hi_gray"].astype(np.float64)
sl = np.maximum(z["sd_lo"].astype(np.float64), 0.5)
sh = np.maximum(z["sd_hi"].astype(np.float64), 0.5)
floor = M.floor_mask(z["static"])
sg64 = cv2.cvtColor(z["static"], cv2.COLOR_BGR2GRAY).astype(np.float64)
solid = (lab == M.FLOOR) | (lab == M.PLANT)
sep = (hi - lo) / np.minimum(sl, sh)
usable = solid & (sep > 4.0) & (hi - lo > 6.0)
H, W = floor.shape
fps = float(src["fps"])

f = np.load(_G.fit_path_of(SID))
rot, scale, dx, dy = float(f["rot"]), float(f["scale"]), int(f["dx"]), int(f["dy"])
grey_art, alpha = WM.art_grey("ascent")


def warp_any(img):
    h0, w0 = img.shape
    Mx = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, scale)
    side = int(max(h0, w0) * scale * 1.6)
    Mx[0, 2] += side / 2 - w0 / 2
    Mx[1, 2] += side / 2 - h0 / 2
    return cv2.warpAffine(np.ascontiguousarray(img, np.float32), Mx, (side, side),
                          flags=cv2.INTER_AREA)


wa = WM._place(warp_any(alpha.astype(np.float32)), np.zeros((H, W), np.float32), dx, dy)
wg = WM._place(warp_any(grey_art), np.zeros((H, W), np.float32), dx, dy)
art_alpha = wa > 0.5
wg = np.clip(wg, 0, 255).astype(np.uint8)

if CACHE.is_file():
    freq = np.load(CACHE)["freq"]
    n = int(np.load(CACHE)["n"])
else:
    cap = cv2.VideoCapture(src["path"])
    acc = np.zeros((H, W), np.float64); n = 0
    for tsec in np.arange(120.0, 1400.0, 12.0):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(tsec * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[box[1]:box[3], box[0]:box[2]]
        if not M.widget_drawn(crop, sg64, floor):
            continue
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)
        acc += usable & ((np.abs(g - hi) / sh) < (np.abs(g - lo) / sl))
        n += 1
    cap.release()
    freq = acc / max(n, 1)
    np.savez(CACHE, freq=freq, n=n)

print(f"{n} frames\n")
q = np.where(usable, freq, 0.0)
always = usable & (q > 0.85)
sometimes = usable & (q > 0.20) & (q < 0.50)
MAIN = 118

print("  art grey under each population (the art's main floor shade is 118):")
print(f"  {'population':<26}{'n':>8}{'median art grey':>18}{'at main shade':>16}")
for nm, m in (("always lit (>85%)", always),
              ("sometimes lit (20-50%)", sometimes),
              ("all usable", usable)):
    mm = m & art_alpha
    if mm.sum() < 50:
        continue
    vv = wg[mm].astype(int)
    print(f"  {nm:<26}{mm.sum():8d}{np.median(vv):18.0f}"
          f"{np.mean(np.abs(vv - MAIN) <= 3) * 100:15.1f}%")

print("\n  the other way round -- always-lit share, BY art shade:")
print(f"  {'art shade':<26}{'n':>8}{'always lit':>13}{'hi-lo median':>14}")
for lo_g, hi_g, nm in ((115, 121, "main floor (118)"),
                       (122, 137, "one step lighter"),
                       (138, 200, "two+ steps lighter"),
                       (0, 114, "darker than main")):
    mm = usable & art_alpha & (wg >= lo_g) & (wg <= hi_g)
    if mm.sum() < 50:
        continue
    print(f"  {nm:<26}{mm.sum():8d}{np.mean(q[mm] > 0.85) * 100:12.1f}%"
          f"{np.median((hi - lo)[mm]):14.1f}")
