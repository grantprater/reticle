r"""Pings on the minimap: what one is, and how to find it while something else decodes.

Detection lives here rather than in `prototypes/ping_scan.py` for the reason
the player gave when he found the prototype opening its own video: *why is the
corpus rescan not including pings?* Because it took a VIDEO PATH and not a
session, so it could only ever be another full decode -- the exact problem
`reticle/passes.py` was built the same afternoon to solve, applied to every
reader except the one written that day. A reader that ships is a reader that
rides the pass, and that is what `PingReader` below is.

What a ping actually is, measured 2026-09-05
--------------------------------------------
the player recorded two clips for this -- a 65 s spam of four types, and a second
clip for the fifth -- and the first thing they settled is what a ping is NOT.

**It does not expand.** At 60 Hz there is nothing at 7.133 s and a full-size
diamond at 7.150 s, which then sits static for its whole life. No growth phase,
no ring, no arcs. So the entity model needs no fourth `extent` value: a ping is
`origin=fixed, bearing=absent, extent=none`, the same parameter shape as a
deployed device. Its identity is in the GLYPH and its LIFETIME.

**The lifetime is a constant, and it is the strongest feature here.** Over
fifteen instances every ping was drawn for either exactly 7.0 s or exactly
10.0 s, with no spread at all at a 10 Hz sample:

    standard        cyan diamond      hue  82     7.0 s   (n=6)
    need help       orange flag       hue  17-18  7.0 s   (n=4)
    watching here   purple eye        hue 145     7.0 s   (n=1)
    danger          red triangle      hue 174    10.0 s   (n=4)
    on my way       yellow stopwatch  hue  32     --      (its own clip)

Danger lasting longer than the rest is worth knowing before anyone tunes a
persistence window: a single threshold at "about 8 seconds" cuts exactly one
class in half.

Why colour is allowed here, given the standing rule
---------------------------------------------------
`CLAUDE.md`: *never test an absolute level against this HUD*, because it is
composited over live scenery. That rule is followed rather than broken, in the
form the same section prescribes -- **structure first, then colour for
identity**.

The structure is `minimap.floor_mask`: the opaque slab. The map body is grey
and nothing behind the widget shows through it, so a SATURATED object on the
floor is by construction something drawn on top. Hue then answers only "which
of the five is it", which is what the convention says level is for.

Take the structure away and this collapses immediately, and the clip proves
it: the warm Sunset scenery reads at hue 10-22 through the semi-transparent
void, the same band as the `need help` flag. A saturation threshold over the
whole widget returned 640 marks of which almost none were pings. **A ping
finder cannot be a colour threshold over the ROI.**

Limits, stated because the numbers look better than they are
-------------------------------------------------------------
* **one map, one widget size, one sitting.** Sunset, bigmap. The hues are of a
  glyph drawn over a grey slab so they ought to be stable, but that is an
  argument, not a measurement -- which is what running this on match footage is
  for.

  **It has now been run on match footage, and the hues held while the
  PRECISION collapsed: 8 real of 31 confirmed on a 31-minute Lotus match,
  against 15 of 15 on the clip.** The clip was recorded solo in a custom game,
  so its widget contained pings and nothing else -- and the thing that made the
  lifetime gate look like a complete detector was the absence of everything a
  real minimap draws. Full numbers and the two hypotheses tested against them
  in `prototypes/ping_match_eval.py`; the classes, none of which the clip could
  have contained:

      ally icon (teal ring + portrait + cone)      13   hue 78-81 vs 82
      warm world scenery at the widget's edge       4   hue 14-15 vs 17
      another minimap icon (yellow triangle)        3   hue 24-35
      red X death mark                              2   hue 174-175 vs 174
      a red team bar across the map                 1   hue 177

  **An ally holding an angle for seven seconds is a standard ping to this
  detector**, on hue, on size and on lifetime. That is the finding, and it is
  not a threshold problem;
* **n=1 for `watching here`**, and `on my way` appears only in its own clip.
  The lifetimes of those two are assumed from the other three, not observed;
* ~~a ping over the VOID is invisible to this~~ -- **ANSWERED by the player,
  2026-09-05, and it is a guarantee rather than a limitation: YOU CANNOT PING
  INTO THE VOID.** *If you ping in a hole it snaps to the nearest minimap
  border; if you ping in the void outside the ping just doesn't work at all.*

  So every ping that exists is on the map body or snapped to its border, and
  the floor-mask gate this detector is built on is not merely convenient -- it
  is aligned with the game's own behaviour. There is no population of pings
  this cannot see, which was the largest unknown in the list above.

  The residue is narrower and worth keeping: a ping SNAPPED to a border sits on
  the white line-work, which `floor_mask` reaches only through its 9 px
  dilation and which is the noisiest part of the widget (BORDER carries the
  highest within-state SD of any class, and the player painted only ~47% of border
  pixels as searchable). Border-snapped pings are the ones to check first on
  match footage, not void pings -- those do not exist;
* **`on my way` (hue 32) sits closer to `need help` (17-22) than any other
  pair.** Those two are what to watch on a different map.

The lifetime is a GATE, and it had to become one
------------------------------------------------
The first run of this reported lifetime as a check beside the answer, and the
check turned out to be the detector. Hue alone found the 15 real pings and
**24 false ones**, every one of them warm Sunset scenery in the `need help`
band, seen through a part of the widget the floor mask does not quite exclude.
Every single false positive lasted under 5.1 s and 19 of the 24 under 2 s;
every true positive matched its class lifetime to within 0.1 s.

So a hue match is a CANDIDATE and the lifetime is what confirms it. That is
the shape this repo's fixes keep having -- the specific test is structural
(how long the game draws the thing), not a tighter threshold on the same
noisy quantity.

Two leaks in the first version of the gate, both worth keeping written down
because each one is a way a persistence test can be fooled:

* **one-sided.** `life >= want - tol` passed a red map bar drawn for 27.2 s
  against `danger`'s 10 s. A lifetime that is too LONG is as disqualifying as
  one that is too short;
* **not contiguous.** Scenery that flickers in and out across the whole clip
  accumulates 41 sightings over a 58 s span; counting frames rather than
  measuring the span called that a 4 s object. A ping is drawn CONTINUOUSLY, so
  the span it was seen over must equal the number of frames it was seen in.

  **That test is now redundant and is kept only as a backstop: contiguity is
  enforced at CONSTRUCTION, in `Grouper`, because testing for it afterwards
  cost a real ping.** A sighting joins a run only if it is adjacent in time as
  well as in space, so a flicker becomes many short runs that die on
  `MIN_FRAMES` instead of one long one that dies on its span. Verified by eye
  on the spam clip: the fourth `danger` was being merged into a longer group
  and thrown away, and it comes back at 43.7 s with an 11.0 s life. The clip
  holds **15** pings -- 6 standard, 4 need help, 1 watching here, 4 danger,
  which is exactly the hand-counted table above -- and the detector now finds
  all 15 rather than 14.

A run truncated by the end of observation is reported UNCONFIRMED rather than
either accepted or dropped -- its lifetime cannot be measured, so the strongest
feature is simply missing. That is not a technicality: the yellow foliage 1.9 s
before the clip stops is still refused, along with four more tail flickers that
used to be rejected on span and are now honestly unmeasurable instead.
Reporting one as a ping would be the pipeline claiming more than its evidence
supports; dropping it silently would be the class of mistake
`reticle/census.py` exists to catch.

Three things a session needs that a 65-second clip did not
-----------------------------------------------------------
Moving this onto a 31-minute match broke three assumptions the clip hid, and
each one is a way a clip-shaped detector fails at session length:

* **"the end of the clip" is not the only place observation stops.** A reader
  bounded by active spans stops at every span end, and `widget_drawn` refuses
  the death screen and the M key wherever they fall. Both are holes in the
  sample train, and a run that ends at one has exactly the problem the
  truncation rule exists for. So the boundary set is derived from the
  timestamps actually OBSERVED (`_boundaries`) rather than named as the last
  one, and the clip end falls out of that as the trivial case;
* **holding the frames does not scale.** The prototype accumulated every crop
  and detected at the end, because the static map is a median and cannot exist
  before the pass is over. At 10 Hz over 65 s that is 440 MB; over this match
  it is 12 GB. The reader takes a floor mask it is GIVEN -- the store already
  caches the static map per session -- so `feed` detects in place and holds
  sightings, not pixels;
* **matching a sighting against every live group is quadratic.** 18 600 frames
  of a busy map build tens of thousands of groups, and the prototype's linear
  scan over all of them is billions of comparisons. `Grouper` indexes groups by
  an 8 px cell and searches the 3x3 neighbourhood, which is the same answer --
  ties broken by creation order exactly as the linear scan's `break` did -- in
  constant time per sighting.
"""

from __future__ import annotations

import cv2
import numpy as np

#: Measured 2026-09-05; see the module docstring for n and for the limits.
#: `hue` is OpenCV's 0-179.
PING_TYPES = [
    ("standard",      (76, 90),   "cyan diamond"),
    ("need_help",     (13, 26),   "orange flag"),
    ("on_my_way",     (28, 38),   "yellow stopwatch"),
    ("watching_here", (138, 155), "purple eye"),
    ("danger",        (166, 179), "red triangle"),
]

#: How long a ping is drawn for. Two values, not one -- see the docstring.
LIFETIME_S = {"standard": 7.0, "need_help": 7.0, "watching_here": 7.0,
              "on_my_way": 7.0, "danger": 10.0}

SAT_MIN, VAL_MIN = 120, 120
AREA = (20, 250)
SIDE = (5, 22)
#: How far apart two sightings may be and still be the same ping.
SAME_PX = 8
#: A ping lasts seconds; fewer frames than this is a flicker, not a mark.
MIN_FRAMES = 5
#: How far an observed lifetime may fall short of the class's and still count.
#: Measured: true positives land within 0.1 s, the worst false positive at
#: 5.1 s against a 7 s class, so anything from 0.5 to 1.8 separates them.
LIFE_TOL_S = 1.0
#: A jump larger than this many sample periods is a hole in the observation,
#: not a stride. 2.5 rather than 2 because OBS output is variable-rate and
#: `sample_multi` keeps phase as a next-timestamp, so consecutive samples
#: already scatter either side of 1/hz.
GAP_PERIODS = 2.5


def classify(hue: int) -> str | None:
    for name, (lo, hi), _ in PING_TYPES:
        if lo <= hue <= hi:
            return name
    return None


class Grouper:
    """Sightings of a fixed mark, collected into CONTIGUOUS runs by position.

    A ping does not move, so two sightings within `SAME_PX` are the same
    object -- but only if they are also adjacent in TIME. A group is a run,
    not a bag, and enforcing that here rather than testing for it afterwards
    is the difference between a clip and a session:

    **over 31 minutes every walkable cell eventually holds a group.** Allies
    walk the whole map, so an unexpiring group at each cell is reached within
    a few rounds -- and a ping placed where a teammate stood ten minutes ago
    then JOINS that group, inherits its ten-minute span, and is thrown away by
    the contiguity test in `resolve` for being what it is not. Measured on
    587c15b07779: 316 groups in one 90 s window, spans up to the full window,
    and nothing at all survived to be confirmed. On a 65 s clip the cells are
    sparse and this never fires, which is why the prototype could not see it.

    Breaking a run at a gap is also strictly the better mechanism for what the
    contiguity test was FOR. Scenery flickering in and out across a clip used
    to accumulate 41 sightings over 58 s and be caught afterwards; it now
    becomes many short runs, each of which dies on `MIN_FRAMES` instead.

    `max_gap` is the one tolerance. It has to exceed a sample period -- an
    ally icon sliding over a ping costs frames, and OBS output is
    variable-rate -- and it must stay far below a lifetime or the merging
    above comes straight back. A ping obscured for longer than it splits into
    two runs and both fail the gate, which loses the ping rather than
    inventing one.

    The index exists only for speed: matching is against each group's FIRST
    sighting, so a group's cell never changes and the 3x3 neighbourhood of a
    candidate's cell contains every group that could possibly match. Ties go
    to the earliest-created live group, which is what a linear scan does by
    breaking on its first hit.
    """

    def __init__(self, hz: float = 10.0, same_px: int = SAME_PX):
        self.same = same_px
        self.max_gap = GAP_PERIODS / hz
        self.groups: list[list[tuple[float, int, int, int]]] = []
        self._cells: dict[tuple[int, int], list[int]] = {}

    def add(self, t: float, x: int, y: int, hue: int) -> None:
        cx, cy = x // self.same, y // self.same
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self._cells.get((cx + dx, cy + dy), ()):
                    if best is not None and i > best:
                        continue
                    g = self.groups[i]
                    if t - g[-1][0] > self.max_gap:
                        continue          # stale: a different object, later
                    _t0, gx, gy, _h = g[0]
                    if abs(x - gx) < self.same and abs(y - gy) < self.same:
                        best = i
        if best is not None:
            self.groups[best].append((t, x, y, hue))
            return
        self._cells.setdefault((cx, cy), []).append(len(self.groups))
        self.groups.append([(t, x, y, hue)])


def sightings(crop: np.ndarray, floor: np.ndarray):
    """Saturated blobs of ping size sitting on the opaque floor.

    The only place pixels are looked at, so it is the whole definition of a
    ping CANDIDATE -- everything after it is persistence.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = (floor & (hsv[:, :, 1] > SAT_MIN)
         & (hsv[:, :, 2] > VAL_MIN)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for k in range(1, n):
        if not AREA[0] <= st[k, 4] <= AREA[1]:
            continue
        if not (SIDE[0] <= st[k, 2] <= SIDE[1] and SIDE[0] <= st[k, 3] <= SIDE[1]):
            continue
        out.append((int(cen[k][0]), int(cen[k][1]),
                    int(np.median(hsv[:, :, 0][lab == k]))))
    return out


def _boundaries(ts: list[float], hz: float) -> list[float]:
    """Instants where observation STOPPED: holes in the sample train, and its end.

    A span end, a stretch of death screen and the end of the capture are the
    same fact to a lifetime measurement -- after this instant the detector
    would not have seen the ping whether it was drawn or not. Deriving them
    from the observed timestamps covers all three without naming any.
    """
    gap = GAP_PERIODS / hz
    out = [ts[i] for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > gap]
    out.append(ts[-1])
    return out


def resolve(grouper: Grouper, ts: list[float], hz: float):
    """Groups -> (confirmed, unconfirmed, rejected). The lifetime gate.

    Rows are `(kind, t0, t1, x, y, hue, n_frames)`.
    """
    if not ts:
        return [], [], []
    bounds = _boundaries(sorted(ts), hz)
    out, unconfirmed, rejected = [], [], []
    for g in grouper.groups:
        if len(g) < MIN_FRAMES:
            continue
        hue = int(np.median([e[3] for e in g]))
        kind = classify(hue)
        if kind is None:
            continue
        t0, t1 = g[0][0], g[-1][0]
        row = (kind, t0, t1, g[0][1], g[0][2], hue, len(g))
        life = len(g) / hz
        want = LIFETIME_S[kind]
        # CONTIGUOUS: a ping is drawn continuously, so the span it was seen
        # over must equal the number of frames it was seen in. Scenery that
        # flickers in and out all clip has a 58 s span and a 4 s count, and it
        # was slipping through the truncation exemption below by happening to
        # be visible in the last frame.
        if (t1 - t0) > life + LIFE_TOL_S:
            rejected.append(row)
            continue
        # Still on screen when observation stopped is not evidence against a
        # ping, so a truncated run is held to the upper bound only.
        truncated = any(0.0 <= b - t1 < LIFE_TOL_S for b in bounds)
        if truncated:
            # The lifetime cannot be checked, so the strongest feature is
            # missing and the row is UNCONFIRMED rather than a ping. The one
            # false positive left on the spam clip is exactly here -- yellow
            # foliage at 63.2 s, 1.9 s before the recording stopped -- and
            # calling it a ping would be the pipeline reporting a number more
            # confident than its evidence.
            (unconfirmed if life <= want + LIFE_TOL_S else rejected).append(row)
        elif abs(life - want) <= LIFE_TOL_S:
            out.append(row)
        else:
            rejected.append(row)
    for lst in (out, unconfirmed, rejected):
        lst.sort(key=lambda r: r[1])
    return out, unconfirmed, rejected


class PingReader:
    """`passes.Reader` that finds pings on frames somebody else decoded.

    One-phase: it is handed the floor mask rather than deriving one, because
    the static map it comes from is a median that cannot exist until the pass
    is over -- and the store already has it cached per session. Give it
    `sgray` too and it refuses widget-absent frames the way `_MinimapPass`
    does; those frames hold ordinary world pixels, which is the population
    every colour test in this repo has eventually tripped over.
    """

    def __init__(self, floor, box, sgray=None, name="ping", hz=10.0, spans=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.box = box
        self.floor = floor
        self.sgray = sgray
        self.g = Grouper(hz)
        self.ts: list[float] = []
        self.n_absent = 0
        self.hits: list = []
        self.unconfirmed: list = []
        self.rejected: list = []

    def feed(self, smp) -> None:
        from .minimap import widget_drawn

        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        if self.sgray is not None and not widget_drawn(crop, self.sgray, self.floor):
            # NOT a sighting and NOT an observation: leaving the timestamp out
            # is what makes `_boundaries` see the hole, so a ping that was on
            # screen when the player pressed M comes back unconfirmed rather than
            # rejected for a life it was never given the chance to live.
            self.n_absent += 1
            return
        t = smp.t_ms / 1000.0
        self.ts.append(t)
        for x, y, hue in sightings(crop, self.floor):
            self.g.add(t, x, y, hue)

    def finish(self):
        self.hits, self.unconfirmed, self.rejected = resolve(self.g, self.ts, self.hz)
        return self.hits

    def events(self, session_id: str) -> list[dict]:
        """Confirmed pings as event rows. Positions are WIDGET pixels."""
        from .version import PING_VERSION

        return [{
            "session_id": session_id,
            "ping_version": PING_VERSION,
            "t_ms": int(t0 * 1000),
            "source": "minimap",
            "kind": kind,
            "x": x, "y": y,
            "frame": "widget",
            "lifetime_s": round(n / self.hz, 1),
            "expected_lifetime_s": LIFETIME_S[kind],
            "hue": hue,
            "drivers": {"origin": "fixed", "bearing": "absent", "extent": "none"},
        } for kind, t0, _t1, x, y, hue, n in self.hits]
