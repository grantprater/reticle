r"""THE FITTED BEARING FLIPS 180 DEGREES, and that is the cone channel's ceiling.

    .\.venv\Scripts\python.exe prototypes\cone_flip.py

Found 2026-09-06 while asking a different question -- what a CARRIED bearing is
worth across a bad frame. The answer to that turned out to be a symptom.

At 15 Hz the change in the self bearing between CONSECUTIVE frames (67 ms) is
bimodal, over 3926 pairs on a06f04a0059f:

    0-10 deg    47.0%   ###########################################
    10-20       12.7%
    20-45        8.2%
    45-120       9.1%
    120-150      6.9%
    150-180     16.1%   <- a second MODE, and it is not rotation

**Nobody turns 180 degrees in 67 ms, one time in six.** That tail is the FIT
flipping, and it is flat at p90 ~160 degrees across every gap from 67 ms to
3 s -- so it does not improve with sample rate, which is what rules out
rotation as the cause. It is the failure `minimap_cone`'s docstring records as
having been fixed by `fit_ring` ("a facing calculation that was ~180 degrees
off from icon fragmentation"); the fix was partial, and nothing measured the
residue until the interpolation question forced it.

**`cov` and `lobe` cannot see it.** The flipped population scores a HIGHER
median lobe than the stable one (0.65 against 0.58) and a slightly lower
coverage (0.46 against 0.50). A flip is a confident answer, which is the worst
kind, and it means no threshold on the existing features removes it.

Why it matters more than the interpolation question it came from: **the
observable area is built out of these bearings**, so roughly a sixth of the
cones drawn into it point backwards. Every SS11 invariant written in terms of
that area inherits the error.

THE CORROBORATOR: the game DRAWS the cone, so ask it
------------------------------------------------------
The lit wedge is the game's own statement of where the player is looking, and
comparing the fitted direction against its opposite is a RELATIVE test over two
regions of one frame -- the shape that has never once been wrong here, and not
the absolute threshold that fails on this widget. With temporal consensus as a
proxy truth (a bearing agreeing with both neighbours against one 180 out from
both), 120 frames each:

    lit fraction in cone(fit) - lit fraction in cone(fit+180)
      stable   median +0.13    80% positive
      flipped  median -0.00    48% positive

**Asymmetric, and honestly so: it endorses a good bearing and DECLINES to
endorse a bad one.** 48% is chance, not evidence of backwardness, so this is a
confirmer rather than a refuter -- the same one-sided shape as the enemy X mark
and the missing tray drop.

Two things about how it is measured, and the first one inverted the result:

* **the LIT FRACTION, not the median lift.** The first version took the median
  lift inside the cone and found nothing (both medians +0.00, 41% against 28%),
  because the drawn cone is a PARTIAL bright region inside the raycast area and
  a median over the whole area is diluted by the part the game did not light.
  Coverage within the structure is the statistic; the aggregate convention
  caught this one on its author;
* **measured on the ERODED floor.** A raw lift over the whole widget returns
  almost entirely wall outlines -- registration and anti-aliasing, not cones --
  which is why an absolute lift threshold was abandoned earlier the same day.
  Eroding 7 px off the floor removes them and leaves a lift that can only be a
  cone.

NOT YET A FIX. Temporal consensus is the strong signal and it defined the
labels here, so it cannot also be the evidence -- the seeding mistake in
another costume. The honest next step is a bearing resolved from BOTH: the
track's own history, which is cheap, and this lit-fraction test, which is
independent of it.
"""
import json, pathlib, sys
import cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from reticle.profiles import PROFILES
from reticle import minimap as M
from reticle import cone as C
from ally_cone import _load, _ang_diff

SID = "a06f04a0059f"
man = json.load(open(next((pathlib.Path.home()/"reticle-store"/"manifests").rglob(f"*{SID}*.json"))))
src = man["source"]; prof = PROFILES[man["source_profile"]]
box = M.minimap_roi_px(prof, int(src["width"]), int(src["height"]))
z = np.load(pathlib.Path.home()/"reticle-store"/"geometry"/f"{SID}.npz")
med, labels = z["static"], z["labels"]
floor = M.floor_mask(med)
passable = floor | (labels == M.BOXEDGE)
sg = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.int16)

# Wall edges dominate a raw lift, so measure only on floor pixels well AWAY
# from any wall -- the interior of the slab, where a lift can only be a cone.
interior = cv2.erode(floor.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
print(f"floor {floor.mean()*100:.1f}%  interior (eroded 7px) {interior.mean()*100:.1f}%")

d = _load(SID, ".hz15")
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
        ser.append((row["t_ms"], best))
ser.sort()

# Temporal consensus as the proxy truth: a bearing agreeing with BOTH
# neighbours is almost certainly right; one 180 out from both is a flip.
STABLE, FLIP = [], []
for i in range(1, len(ser) - 1):
    a, b, c = ser[i - 1][1]["facing"], ser[i][1]["facing"], ser[i + 1][1]["facing"]
    if ser[i + 1][0] - ser[i - 1][0] > 250:
        continue
    if _ang_diff(a, b) < 25 and _ang_diff(b, c) < 25:
        STABLE.append(i)
    elif _ang_diff(a, b) > 150 and _ang_diff(b, c) > 150 and _ang_diff(a, c) < 40:
        FLIP.append(i)
print(f"proxy truth from temporal consensus: {len(STABLE)} stable, {len(FLIP)} flipped")

cap = cv2.VideoCapture(src["path"])
fps = float(src["fps"])


def lift_ratio(crop, fit, deg):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.int16)
    lift = g - sg
    m = C.raycast(passable, fit["cx"], fit["cy"], deg, visible=floor) & interior
    if m.sum() < 40:
        return None
    # LIT FRACTION, not a median: the drawn cone is a partial bright region
    # inside the raycast area, so a median over the whole area is diluted by
    # the part the game did not light. "How much of this cone is actually lit"
    # is coverage within the structure -- the shape CLAUDE.md prescribes.
    return float((lift[m] > 20).mean())


rng = np.random.default_rng(5)
out = {}
for name, idx in (("stable", STABLE), ("flip", FLIP)):
    pick = rng.choice(len(idx), size=min(120, len(idx)), replace=False)
    vals = []
    for k in pick:
        i = idx[int(k)]
        t_ms, fit = ser[i]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[box[1]:box[3], box[0]:box[2]]
        fwd = lift_ratio(crop, fit, fit["facing"])
        back = lift_ratio(crop, fit, fit["facing"] + 180.0)
        if fwd is None or back is None:
            continue
        vals.append(fwd - back)
    v = np.array(vals)
    out[name] = v
    print(f"  {name:7s} n={len(v):4d}  median lift(fitted) - lift(fitted+180): "
          f"{np.median(v):+6.2f}   p25 {np.percentile(v,25):+6.2f}  p75 {np.percentile(v,75):+6.2f}"
          f"   share > 0: {np.mean(v>0)*100:.0f}%")
cap.release()
if "stable" in out and "flip" in out and len(out["flip"]):
    s, f_ = out["stable"], out["flip"]
    print(f"\n  If the drawn cone corroborates the fit, `stable` sits ABOVE zero")
    print(f"  and `flip` BELOW it. Separation by sign: stable {np.mean(s>0)*100:.0f}% "
          f"vs flip {np.mean(f_>0)*100:.0f}%")


# ---------------------------------------------------------------- area cost
# `python prototypes/cone_flip.py --area`
#
# WHAT THE GATE COSTS. A refusal can only SHRINK the observable area, so the
# question is whether removing the backwards cones is affordable. Measured over
# 897 frames in three 20 s windows of a06f04a0059f at 15 Hz:
#
#     configuration           cones/frame   observable % of floor
#     raw bearings, 56 deg           3.53           24.8   (median 20.5)
#     raw bearings, 51.5             3.53           23.7   (median 20.0)
#     GATED bearings, 51.5           3.06           21.5   (median 18.9)
#
# **13.1% of area for the whole change**, of which roughly a third is the
# narrower half-angle and two thirds the gate. Cones overlap heavily, so
# refusing 13% of them costs far less than 13% of the area -- which is why the
# gate is affordable at all. And the direction is the safe one: a too-large
# observable area silently discards real enemy observations, a too-small one
# only fails to fire.
