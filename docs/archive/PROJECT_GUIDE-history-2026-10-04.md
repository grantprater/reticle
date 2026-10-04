# PROJECT_GUIDE history moved out on 2026-10-04

`PROJECT_GUIDE.md` exceeded its word budget, so this history left its
*Open defects* section. The guide keeps the rule and a link here.

## The minimap position reader before `minimap-0.2.0`

From the bullet *The M key removes the minimap*:

**The shipped minimap position reader had no widget guard of any kind** until
`minimap-0.2.0` adopted `minimap.widget_drawn`; before it, `cmd_minimap` read
every frame inside an active span. Measured over all 27757 frames of
`a06f04a0059f` at 15 Hz:

      usable()  refuses    614  (2.2%)
      drawn()   refuses   1394  (5.0%)
      the gap             780  (2.8%) -- kept by usable(), refused by drawn()
      harvested from those frames:  3605 self candidates, 4178 ally

So **5% of the shipped position track was built on frames with no widget in
them**, and adopting `usable()` alone would recover under half of that. The
detections are not few: widget-absent frames yield 2.6 self candidates each,
because `self_rings` is looking at open scenery.

Closing it moves stored numbers, which is why it was measured first rather
than patched -- but 5% is far past the level at which the position track's
validation (the X-mark and chokepoint ground truths) can be assumed to still
hold, so both were re-run against the guard (`reticle/version.py`,
`minimap-0.2.0`).
