r"""Who is ALIVE, read as per-frame state off the roster bars.

CLAUDE.md has described this since 2026-08-25 and nothing had built it:

> The roster bars draw a portrait only for a player who is *alive* -- it
> disappears on death -- so counting portraits gives both teams' alive counts
> as a per-frame state. No integration of killfeed events, no error
> accumulation. [...] It is the densest validity signal available and it costs
> one new ROI.

The ROIs were already there (`hud_roster`, `hud_roster_enemy`). `l1/hud` has 34
columns and not one of them is a roster read, so "how many allies are alive"
could not be asked of stored data at all -- which is what blocked every count
constraint the object layer wants (`prototypes/widget_objects.py`).

What separates a drawn portrait from an empty slot
---------------------------------------------------
Measured 2026-09-06 on 587c15b07779, six frames x ten slots read by eye:

    statistic     alive             dead            separates
    laplacian     18.87 .. 34.44    1.87 ..  4.53   YES, 60/60
    health pill    0.00 ..  0.63    0.00 ..  0.21   no,  43/60
    saturation    64.43 ..143.52   56.26 ..151.05   no,  34/60

A factor of four, with an empty band between. **The mechanism is structural
rather than lucky, which is why it is worth trusting further than six frames
normally buys:** the roster bar is a semi-transparent tinted panel, so whatever
is behind it arrives DIMMED AND BLURRED, while the portrait is crisp art
composited on top. Detail is therefore a property of the compositing, not of
the scene -- an empty slot over foliage scored 3.5 where a portrait over the
same background scored 33.

The health pill was the obvious candidate and it loses. CLAUDE.md already
records why (*the roster bar's white health pips vanishing against a white
wall*) and the measurement agrees: 43 of 60.

Relative first, with a floor underneath -- both, not either
-------------------------------------------------------------
The standing rule forbids resting on an absolute level here, and pure relative
cannot answer the two cases that matter most: everyone alive, and everyone
dead. Both are "no gap between slots".

So the read uses the structure the game itself provides. **Survivors PACK
toward the scoreline keeping team order** (CLAUDE.md, confirmed by eye here --
allies pack right, enemies pack left), so the occupied slots are a CONTIGUOUS
RUN anchored at the inner edge. Counting is therefore finding ONE BOUNDARY, not
classifying five slots independently, and the count is chosen as the split that
maximises the gap between the dimmest occupied slot and the brightest empty one
-- self-calibrating per frame. `DETAIL_FLOOR` only rules out a split that would
call something occupied when nothing on the bar is crisp at all, which is what
makes the all-dead case resolve.

What this is FOR, and the direction that must not be reversed
---------------------------------------------------------------
The roster is STATE and the killfeed is EVENTS, so a running killfeed total
should always agree with the roster count, and where they diverge an entry was
missed. That is the densest validity signal in the project -- it checks every
sampled frame where the scoreboard offers at most fifty checks a match.

**But a channel used as a PRIOR cannot also be the evidence that validates it.**
This module is calibrated against killfeed-derived counts once; after that, the
killfeed is the thing being audited and the roster is the auditor. Recording
which direction is in force at any time is not pedantry here -- circular
validation has already cost this repo real work twice (`plant_probe`'s controls
drawn from the population under test, and seeding `minimap_agent` with
provisional rows).

KNOWN DEFECT: an UNDRAWN roster reads as 0, not as unreadable
--------------------------------------------------------------
Found by `roster_alive.py --stored` on `c40d950031bb` the day the table
landed, which is the audit doing its job on its first run. **9.6% of stored
rows read `(0, 0)`**, and every one of them falls outside a round -- 0:08 to
1:53, the pre-match menu and loading, plus 16:06-16:09 after the final round.
Not one occurs mid-round.

The mechanism is in `alive_from_detail`. When nothing on the bar is crisp,
every split with an occupied slot is rejected by `DETAIL_FLOOR`, so `n = 0`
wins by elimination and is returned as a CONFIDENT count. "No roster is drawn"
and "all five are dead" are the same answer, and they should not be.

One cause, both of this session's imperfect numbers: the three `-10` probes in
the cross-channel check are round 0's first three, and the two "starts at 5"
failures are round 0's two teams.

**Not patched, deliberately.** `DETAIL_FLOOR`'s whole stated purpose is to
resolve the all-dead case, so returning `None` there contradicts the reason it
exists, and one session is not enough to reverse that on. The two candidate
fixes are a drawn/undrawn test of the kind `minimap.widget_drawn` does for the
widget, or bounding the reader to rounds rather than the whole capture. Both
need a second session. Until then `(0, 0)` is the marker: it cannot happen
inside a round, so treat it as not-in-round rather than as a count, and
`reticle scan` prints the rate for exactly that reason.

**Both sessions now exist, and they show the defect has a MIRROR that matters
more (2026-09-07).** A drawn-but-empty bar -- a team that has actually been
wiped -- sits at 2-8 detail, which vetoes every occupied split and then loses
`n = 0` to the `-1.0` sentinel, so it reads `None`. Only a near-black bar
reaches 0. So the two answers are swapped from what this section describes: an
UNDRAWN bar reads 0, and a WIPED team reads `None`. The audit loses its most
informative windows that way, since a wipe is a round outcome.

The two candidate fixes are unchanged and the choice is still open. What is new
is that the obvious separator has been tried and FAILED: cross-slot spread does
not distinguish the two at corpus scale (`docs/ROSTER_FINDINGS.md`).

WHAT IS STORED: the EVIDENCE, not just the answer
---------------------------------------------------
`roster-0.2.0` writes `detail_ally` / `detail_enemy` beside the counts, so any
change to `alive_from_detail` is a re-derivation over `l1/roster` rather than a
re-read of the video. `ROSTER_SPLIT_VERSION` stamps the rule; `ROSTER_VERSION`
stamps the pixels, and `Store.has_roster` keys only on the latter.
`prototypes/roster_split_eval.py` is what that buys: it scores candidate rules
against each other, and against the killfeed audit, at no decode cost.
"""

# Three further defects are localized in docs/ROSTER_FINDINGS.md, all confirmed
# by rendering the source frames, none patched:
#
#   1483s on 587c15b07779   two portraits, returns one. The largest ABSOLUTE
#       detail gap falls between the portraits as empty-slot background detail
#       rises. Both clear DETAIL_FLOOR, so the floor is not the fix. A ratio
#       gap fixes it and moves five other cells in the whole corpus, so the
#       corpus cannot say whether it is right;
#   158s on 587c15b07779    all five enemies DEAD, bar drawn, returns None.
#       See the note above: the floor exists to resolve this case and only
#       reaches n=0 on a near-black bar. Pinned by a test;
#   962s on c40d950031bb    five portraits visible under a wipe transition that
#       dims the bar unevenly, returns one. No split over per-slot detail can
#       answer a non-uniform fade; the reader has to refuse. Confined to
#       outside rounds on this corpus (0.0-0.1% of in-round rows).

from __future__ import annotations

import cv2
import numpy as np

from .profiles import Profile

#: Both teams field five.
N_SLOTS = 5
#: Fraction of the bar's height that holds portrait art rather than the health
#: pill beneath it. The pill is deliberately excluded -- it is the weaker
#: signal and it fails against bright scenery.
ART_FRAC = 0.62
#: Mean |Laplacian| below which NOTHING on the bar is crisp, so no split can be
#: called occupied. Permissive on purpose: it exists to resolve the all-dead
#: case, not to decide what counts as a portrait. Measured band is 4.53 (dead)
#: to 18.87 (alive); this sits well inside it and nowhere near either edge.
DETAIL_FLOOR = 9.0


def roster_rois(profile: Profile, w: int, h: int):
    """(ally, enemy) roster boxes in pixels, or None where the profile lacks one."""
    by = {r.name: r for r in profile.rois}
    def px(n):
        return by[n].pixels(w, h) if n in by else None
    return px("hud_roster"), px("hud_roster_enemy")


def slot_detail(crop: np.ndarray) -> list[float]:
    """Per-slot crispness of the portrait band. Five numbers, left to right."""
    if crop is None or crop.size == 0:
        return [0.0] * N_SLOTS
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    art = g[: max(1, int(g.shape[0] * ART_FRAC))]
    w = art.shape[1] / float(N_SLOTS)
    out = []
    for i in range(N_SLOTS):
        s = art[:, int(i * w):int((i + 1) * w)]
        out.append(float(np.abs(cv2.Laplacian(s, cv2.CV_32F)).mean())
                   if s.size else 0.0)
    return out


def alive_from_detail(detail: list[float], pack_right: bool) -> int | None:
    """How many are alive, given the run is anchored at the scoreline edge.

    Returns None when the frame cannot be read -- the roster is covered, or the
    split is ambiguous -- rather than guessing a count. A guessed alive count
    is worse than none: it would silently corrupt the killfeed audit this
    exists to provide.
    """
    if not detail or len(detail) != N_SLOTS:
        return None
    # Occupied slots run inward from the scoreline: allies pack right, enemies
    # pack left. Order the slots so index 0 is always the innermost.
    seq = list(reversed(detail)) if pack_right else list(detail)
    best, best_gap = None, -1.0
    for n in range(0, N_SLOTS + 1):
        occ, emp = seq[:n], seq[n:]
        if occ and min(occ) < DETAIL_FLOOR:
            continue                      # would call a blurred slot occupied
        gap = ((min(occ) if occ else float("inf"))
               - (max(emp) if emp else float("-inf")))
        if not occ:
            gap = -max(emp) if emp else 0.0
        elif not emp:
            gap = min(occ)
        if gap > best_gap:
            best, best_gap = n, gap
    return best


def slot_details(frame: np.ndarray, profile: Profile, w: int, h: int):
    """(ally, enemy) per-slot detail vectors, each None where the ROI is absent.

    **This is the OBSERVATION; the count is the ADJUDICATION.** Splitting them
    is what lets a split rule be re-evaluated from stored data instead of from
    video: ten floats per frame answer every question `alive_from_detail` can
    be asked, and re-deriving a count from them costs no decode at all. The
    original table stored only the count, so `docs/ROSTER_FINDINGS.md`'s "next
    experiment" needed a 127-second re-read of a session already read.
    """
    ra, re = roster_rois(profile, w, h)
    out = []
    for roi in (ra, re):
        if roi is None:
            out.append(None)
            continue
        x0, y0, x1, y1 = roi
        out.append(slot_detail(frame[y0:y1, x0:x1]))
    return out[0], out[1]


def alive_counts(frame: np.ndarray, profile: Profile, w: int, h: int):
    """(allies, enemies) alive, each None when unreadable."""
    da, de = slot_details(frame, profile, w, h)
    return (None if da is None else alive_from_detail(da, True),
            None if de is None else alive_from_detail(de, False))


class RosterReader:
    """`passes.Reader` for alive counts. Per-frame STATE, so it wants density.

    Rides whatever pass is happening, exactly as `PingReader` does -- this is
    state rather than events, so it costs no seeks of its own and nothing here
    justifies opening the file.
    """

    def __init__(self, profile, wh, name="roster", hz=2.0, spans=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.profile = profile
        self.w, self.h = wh
        self.rows: list[dict] = []

    def feed(self, smp) -> None:
        # Read the detail ONCE and adjudicate from it, rather than calling
        # `alive_counts` and recomputing the Laplacian to store the evidence.
        da, de = slot_details(smp.frame, self.profile, self.w, self.h)
        self.rows.append({
            "frame_idx": smp.frame_idx, "t_ms": smp.t_ms,
            "alive_ally": None if da is None else alive_from_detail(da, True),
            "alive_enemy": None if de is None else alive_from_detail(de, False),
            "detail_ally": da, "detail_enemy": de,
        })

    def finish(self):
        return self.rows
