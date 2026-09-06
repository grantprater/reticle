r"""Window refinement on the ping detector: decide on the EDGES, not the run.

    .\.venv\Scripts\python.exe prototypes\ping_edge_eval.py

the player, 2026-09-06: *we're only detecting things that show up on the 2hz
schedule... is there a way to improve accuracy by looking at somewhat nearby
frames?* This is that, applied to the place with a measured failure rate.

The ping detector's gate looks only INSIDE an object's own run, and a teammate
who stands still for seven seconds is, within that run, indistinguishable from
a ping. Outside it they are not: **a ping appears from nothing and vanishes to
nothing**, which is what a 7.0 s lifetime means. So the separating question is
about the run's EDGES, and `reticle.refine.edges` answers it with two short
windows read at native rate.

Result on 587c15b07779, against `ping_match_eval`'s by-eye labels:

    gate   kept   real    prec   recall   what it removes
    ----   ----   ----    ----   ------   ---------------
     --      31      8     26%     100%   nothing (shipped)
    0.20     19      8     42%     100%   ally x7, world x2, xmark x2, bar x1
    0.10     15      7     47%      88%   ally x8, world x3, xmark x2, icon x1
    0.05      9      6     67%      75%   ally x11, world x4, xmark x2, icon x2

**Precision 26% -> 42% at NO recall cost**, and every `world`, `xmark` and
`bar` false positive dies. Tightening past that trades recall for precision on
the ally class, which is the only class the edges do not fully resolve -- some
teammates genuinely do arrive, stand still and leave, which is a ping's
signature exactly.

Two things this measurement had to get right, both of which the first version
got wrong:

* **the after-window must not butt against the run's end.** `t1` is the
  MEASURED end, which at a 10 Hz sample lands up to a period early, so the
  window read the ping's own tail and every real ping scored 0.32-0.43 --
  looking like an object that persists. `refine.edges` takes a `guard_ms`;
* **a window off the end of the capture is a REFUSAL, not a zero.** Reporting
  0.0 there would assert the object appeared from nothing on no evidence.

The labels are mine, so this falsifies and does not license: it demonstrates
the mechanism pays, and a shipped threshold still wants the.
"""

import sys
sys.path.insert(0, r"C:\Users\user\reticle")

import numpy as np
from reticle.store import Store
from reticle.profiles import get_profile
from reticle.minimap import minimap_roi_px, floor_mask
from reticle import ping as P
from reticle.refine import edges

SID = "587c15b07779"
PAD_MS = 1200.0
NEAR_PX = 6

TRUTH = (["ally"] * 6 + ["p"] + ["ally"] * 3 + ["p"] + ["ally"] * 2
         + ["world", "ally", "world", "world", "world", "p", "icon", "xmark",
            "bar", "p", "ally", "icon", "p", "p", "icon", "xmark", "p", "p"])

st = Store()
man = st.read_manifest(SID)
src = man["source"]
prof = get_profile(man["source_profile"])
box = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
x0, y0, x1, y1 = box
floor = floor_mask(st.read_static_map(SID))
rows = st.read_events("ping", SID)
assert len(rows) == len(TRUTH)

print(f"{'#':>3} {'truth':<7}{'kind':<14}{'before':>8}{'after':>8}{'edge':>8}")
res = []
for i, r in enumerate(rows):
    px, py = r["x"], r["y"]

    def probe(fr, px=px, py=py):
        crop = fr[y0:y1, x0:x1]
        for sx, sy, _h in P.sightings(crop, floor):
            if abs(sx - px) <= NEAR_PX and abs(sy - py) <= NEAR_PX:
                return True
        return False

    t0 = r["t_ms"]
    t1 = t0 + r["lifetime_s"] * 1000.0
    b, a = edges(src["path"], t0, t1, probe, PAD_MS, float(src["fps"]))
    # "clean edges" = absent both sides. None (window off the capture) is a
    # refusal and must not be read as absent.
    res.append((TRUTH[i], b, a))
    edge = None if (b is None or a is None) else max(b, a)
    fb = "  --" if b is None else f"{b:6.2f}"
    fa = "  --" if a is None else f"{a:6.2f}"
    fe = "  --" if edge is None else f"{edge:6.2f}"
    print(f"{i:>3} {TRUTH[i]:<7}{r['kind']:<14}{fb:>8}{fa:>8}{fe:>8}")

print()
for name, j in (("before", 1), ("after", 2), ("max of the two", None)):
    def val(r, j=j):
        if j is None:
            return None if (r[1] is None or r[2] is None) else max(r[1], r[2])
        return r[j]
    print(f"--- {name} ---")
    for cls in ("p", "ally", "icon", "xmark", "bar", "world"):
        v = sorted(x for x in (val(r) for r in res if r[0] == cls)
                   if x is not None)
        if v:
            print(f"  {cls:<7} n={len(v):<3} {v[0]:.2f} .. {v[-1]:.2f}"
                  f"   median {v[len(v)//2]:.2f}")
    pv = [val(r) for r in res if r[0] == "p" and val(r) is not None]
    av = [val(r) for r in res if r[0] == "ally" and val(r) is not None]
    if pv and av:
        print(f"  ping {min(pv):.2f}..{max(pv):.2f}   ally {min(av):.2f}..{max(av):.2f}"
              f"   PING/ALLY SEPARATES: {max(pv) < min(av)}")
        scored = [(r[0], val(r)) for r in res if val(r) is not None]
        best = max(((sum(1 for t, e in scored if (e <= th) == (t == "p")), th)
                    for th in np.arange(0, 1.005, 0.01)), key=lambda x: x[0])
        print(f"  best split over ALL classes: {best[0]}/{len(scored)} "
              f"at <= {best[1]:.2f}")
    print()



print("=" * 62)
print("what the edge test does to the SHIPPED confirmations")
hdr = "{:>8}{:>7}{:>7}{:>8}{:>9}   {}".format(
    "gate", "kept", "real", "prec", "recall", "what it removes")
print(hdr)
tot_p = sum(1 for r in res if r[0] == "p")
for th in (0.00, 0.02, 0.05, 0.10, 0.20):
    kept = [r for r in res if r[1] is not None and r[2] is not None
            and max(r[1], r[2]) <= th]
    tp = sum(1 for r in kept if r[0] == "p")
    gone = {}
    for r in res:
        if r not in kept and r[0] != "p":
            gone[r[0]] = gone.get(r[0], 0) + 1
    line = "{:8.2f}{:>7}{:>7}{:7.0f}%{:8.0f}%   {}".format(
        th, len(kept), tp, tp / max(1, len(kept)) * 100,
        tp / max(1, tot_p) * 100,
        ", ".join("{} x{}".format(k, v) for k, v in sorted(gone.items())))
    print(line)
print("")
print("shipped (no edge test): kept 31, real {}, prec {:.0f}%, recall 100%".format(
    tot_p, tot_p / 31 * 100))
