"""PROTOTYPE: screen-space enemy detection, scored against hand labels.

    python prototypes/enemy_detect_eval.py <session> [thr k area ar fill hmin ck]

Best measured so far, on 150 hand-labelled frames of 9acf02f98283:
**77% recall, 14% precision, 1.5 false positives per frame.** Good enough to
feed a tracker, not good enough to use per-frame.

How it got there, because the wrong turns are the useful part
-------------------------------------------------------------
The enemy outline is a **rim light**: red *relative to what it borders*, not red
in absolute terms. Against a dark wall it is vivid; against Ascent's terracotta
it is barely there. Every absolute test failed accordingly:

    absolute red, S>150             53% recall,  3% precision
    + hollow-rim shape filter       30%         10%
    top-hat on Lab a*               85%          6%
    + shape filters                 57%         32%
    + shape tests only on big blobs 75%         11%
    + vertical closing              77%         14%

A morphological **top-hat on Lab's a\* channel** is what works. Top-hat keeps
structures thinner than its kernel and removes anything larger, whatever the
background level -- which is exactly the difference between a 1-4 px rim and a
brick wall, and exactly what a threshold cannot express.

Three separate misreadings, each fixed by looking at pixels rather than at a
summary statistic:

1. **The outline is a rim, not a fill.** Cost four rounds of threshold tuning
   before anyone looked at a labelled crop.
2. **A shape prior needs the shape to exist.** Demanding hollowness of a sliver
   of an enemy -- a shoulder past a corner, which is where peeking happens --
   asks a question with no answer, and the filter answers no. Shape tests now
   apply only to blobs big enough to be a body.
3. **A broken contour is not a small object.** The rim is interrupted by the
   body and by limbs, so connected components shattered one enemy into fragments
   that each failed the size tests. Rendering the misses showed the top-hat
   response containing an unmistakable human shape in *every* one. A vertically
   biased closing kernel bridges them, because a person is taller than wide.

That third one also explains why raising `area` had seemed to trade recall for
precision: it was selecting for enemies whose rims happened to be continuous,
not for real detections, so every operating point along it was bad.

What did not work
-----------------
A **width profile** -- blob width per row, matched against a template mined from
the labels -- separates only about 1.8 to 1 (50% of enemies against 28% of false
positives). The signature is visibly real: enemies average a narrow head, a
shoulder peak, a taper and narrow feet, where false positives are nearly flat.
The distributions simply overlap too much.

That test is also compromised and worth redoing: it measured the profile on the
*closed* mask, and the vertical kernel that fixes grouping smooths away the very
detail a profile test needs. The honest version computes the profile from the
raw top-hat mask inside the merged bounding box.

Where to go next
----------------
Precision is the remaining problem and **temporal consistency is the strongest
unused signal**: a real enemy persists across frames and moves plausibly, an
architectural edge does not. That is what took the minimap tracker from 5.5%
bad jumps to 1.5%, and it is untested here only because the labels are isolated
frames and cannot score a tracker.

It can be validated without more labelling. The killfeed is an anchor: before
every tracked kill an enemy was demonstrably visible, so "was an enemy tracked
in the two seconds before a kill" measures sequence-level recall for free across
all fifteen sessions. It is biased toward enemies about to die, but it tests the
tracker rather than the frame detector, which is exactly the gap.
"""
import json, sys
from pathlib import Path
import numpy as np, cv2
STORE = Path.home()/"reticle-store"
SID  = sys.argv[1]
THR  = int(sys.argv[2]) if len(sys.argv) > 2 else 30      # top-hat strength
K    = int(sys.argv[3]) if len(sys.argv) > 3 else 11      # kernel, > rim width
AREA = int(sys.argv[4]) if len(sys.argv) > 4 else 60
AR   = tuple(float(x) for x in (sys.argv[5] if len(sys.argv) > 5 else "0.7,7.0").split(","))
FILL = tuple(float(x) for x in (sys.argv[6] if len(sys.argv) > 6 else "0.0,0.7").split(","))
HMIN = int(sys.argv[7]) if len(sys.argv) > 7 else 12
CK   = int(sys.argv[8]) if len(sys.argv) > 8 else 9

man = json.loads((STORE/"manifests"/f"{SID}.json").read_text()); src=man["source"]; fps=float(src["fps"])
rows={}
for l in (STORE/"labels"/"enemies"/f"{SID}.jsonl").read_text().splitlines():
    if l.strip(): r=json.loads(l); rows[r["t_ms"]]=r
rows=[r for r in rows.values() if not r.get("uncertain")]

def hud_mask(h,w):
    m=np.ones((h,w),bool); m[:120,:]=False; m[h-190:,:]=False
    m[:360,:360]=False; m[60:360,w-520:]=False; return m

KER = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (K,K))
def detect(fr):
    h,w = fr.shape[:2]
    lab = cv2.cvtColor(fr, cv2.COLOR_BGR2LAB)
    a = lab[:,:,1]                                  # red-green opponent axis
    top = cv2.morphologyEx(a, cv2.MORPH_TOPHAT, KER)
    detect.top = top
    m = ((top > THR) & hud_mask(h,w)).astype(np.uint8)
    # Join the rim into ONE region before measuring it. The rim is broken by the
    # body, by limbs and by occlusion, so connected components shatters a single
    # enemy into fragments that each fail the size tests -- the feature found
    # them, the grouping threw them away. A human is taller than wide, so the
    # kernel is too: it bridges vertically without merging neighbours sideways.
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CK, CK*2)))
    n,l2,st,cen = cv2.connectedComponentsWithStats(m, 8)
    out=[]
    for i in range(1,n):
        x,y,bw,bh,ar = st[i]
        if ar < AREA or bh < HMIN: continue
        f = ar/max(bw*bh,1)
        # Hollowness only means something on a whole model. A sliver of an enemy
        # -- a shoulder past a corner, which is where peeking actually happens --
        # has no interior to be hollow, and demanding one filters out precisely
        # the detections that matter most. So the shape tests apply to blobs big
        # enough to be a body, and small ones get through on contrast alone and
        # are left for the tracker to confirm or discard.
        big = bw >= 14 and bh >= 30
        if big and not (FILL[0] <= f <= FILL[1]): continue
        if big and not (AR[0] <= bh/max(bw,1) <= AR[1]): continue
        # the interior must be *less* red than the rim -- a model sits inside an
        # outline, so the middle is the agent, not more outline
        ix0, iy0 = x + bw//4, y + bh//4
        ix1, iy1 = x + bw - bw//4, y + bh - bh//4
        if bw >= 14 and bh >= 24 and ix1 > ix0 and iy1 > iy0:
            inner = top[iy0:iy1, ix0:ix1]
            if inner.size and float((inner > THR).mean()) > 0.45: continue
        out.append((x,y,bw,bh,ar))
    return out

cap=cv2.VideoCapture(str(src["path"])); PAD=14
st_={p:dict(tp=0,fn=0,fp=0,nt=0) for p in ("uniform","event")}
for r in rows:
    cap.set(cv2.CAP_PROP_POS_FRAMES,int(round(r["t_ms"]/1000.0*fps))); ok,fr=cap.read()
    if not ok: continue
    dets=detect(fr); pool=st_[r["pool"]]
    players=[(m["x"],m["y"]) for m in r.get("marks",[]) if m["kind"]=="player"]
    others =[(m["x"],m["y"]) for m in r.get("marks",[]) if m["kind"] in ("corpse","deployable","revealed")]
    used=set()
    for (px,py) in players:
        hit=None
        for j,(x,y,bw,bh,ar) in enumerate(dets):
            if j in used: continue
            if x-PAD<=px<=x+bw+PAD and y-PAD<=py<=y+bh+PAD: hit=j; break
        if hit is None: pool["fn"]+=1
        else: pool["tp"]+=1; used.add(hit)
    for (px,py) in others:
        for j,(x,y,bw,bh,ar) in enumerate(dets):
            if j in used: continue
            if x-PAD<=px<=x+bw+PAD and y-PAD<=py<=y+bh+PAD: used.add(j); pool["nt"]+=1; break
    pool["fp"]+=len(dets)-len(used)
cap.release()
t={k:sum(s[k] for s in st_.values()) for k in ("tp","fn","fp","nt")}
rec=t["tp"]/max(t["tp"]+t["fn"],1); pre=t["tp"]/max(t["tp"]+t["fp"],1)
print(f"tophat>{THR} k={K} area>={AREA} h>={HMIN} ck={CK} ar={AR} fill={FILL}:  TP {t['tp']:3d}  FN {t['fn']:3d}  FP {t['fp']:4d}  "
      f"nontgt {t['nt']:2d}   recall {rec*100:5.1f}%  precision {pre*100:5.1f}%  "
      f"FP/frame {t['fp']/max(len(rows),1):4.1f}")
