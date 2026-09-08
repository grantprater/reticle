r"""Identity-conditional tracking: what a track is ALLOWED to do next.

    python -m reticle.track --self-test

Recorded 2026-09-06, giving the direction for the minimap entity model:

> identity-based identification of entities with their temporal evolution,
> subject to the invariants of their specific identity (most agents cannot
> teleport or dash, certain abilities have certain durations, movement
> characteristics, etc.)

The design doc's §6 is the argument; this is the code. The one idea: **a
motion model belongs to an IDENTITY, not to the tracker.** A single
constant-velocity prior -- which is what the plan first proposed -- would fight
the truth for exactly the entities that matter here. A Cypher cam rotates and
never translates. A teleport is a LEGAL discontinuity for five agents. A ping
is static with a lifetime measured to 0.1 s. One prior calls all three faults.

What this is not
----------------
**Not a Kalman filter, and deliberately.** A Kalman gate is a Gaussian on
position error, and almost every constraint below is a HARD one -- a hue, a
lifetime, a speed ceiling that is a fact about the game rather than a
distribution. The interesting content is the admissibility rule, not the
covariance, and wrapping it in a filter would hide the part that carries the
domain. When continuous smoothing is wanted it goes on top of this, not
instead of it.

**Not an identity assigner.** `admits` answers *may this class have done
that*, which is a falsifier. The inverse -- concluding a class from behaviour
-- is the circularity §6 names: identity constrains the track and the track
evidences identity, and collapsing the two is the seeding mistake in a fourth
costume. Identity is supposed to arrive from somewhere independent (the
scoreboard lineup, the tray's cast times, the killfeed, the roster) and this
module's job is to say which identities that arrival is CONSISTENT with.

Every number here is recorded elsewhere in the repo and cited
------------------------------------------------------------
Nothing below was invented for this file, which is the point of §6's
inventory: the invariants existed and nothing consumed them.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

#: Top speed of a real track, widget px/s. `minimap.RUN_PX`, measured rather
#: than derived -- every filtered track sits under it and every misdetection
#: blew far past it. Imported rather than restated so there is one definition.
from .minimap import MIN_ICON_SEPARATION_PX, RUN_PX

#: Ping lifetimes, seconds. `ping.LIFETIME_S`, exact to 0.1 s at a 10 Hz
#: sample. Imported for the same reason.
from .ping import LIFETIME_S

TRACK_VERSION = "track-0.3.0"

#: A dash is continuous motion that nonetheless clears the walk ceiling over a
#: sample interval. Jett, Neon and Waylay's Q. **This is a bound, not a
#: measurement**, and `prototypes/jump_census.py` has since shown it cannot be
#: turned into one from data in hand:
#:
#:     over 102,239 steps on five sessions, the speed distribution above the
#:     walk ceiling is a SMOOTH DECAY, not bimodal -- 40.7% of refused steps
#:     sit in 45-60 px/s, 75.2% within 2x the ceiling, and there is no bump
#:     anywhere that a dash could be.
#:
#: So there is no gap to put a threshold in, and at 4x this class absorbed
#: 90.5% of all refusals -- a bound explaining everything rather than a model
#: explaining something. A step admitted only by this is reported WEAK, and
#: the census refuses to quote a defect rate that rests on it.
#:
#: What would fix it: a session where a dash agent was played, tagged as such.
#: None of the five sessions with a minimap track records the agent at all.
DASH_PX_S = RUN_PX * 4.0

#: Beyond this, no continuous motion explains the step at any speed, so the
#: only remaining legal explanations are a teleport or a detection fault. The
#: widget is ~465 px across, so half of it in one sample is not walking.
#:
#: **This is a bound on the impossible and it is NOT a teleport detector.**
#: `prototypes/cast_motion.py` measured the largest step in the 3 s after each
#: teleport cast, agent taken from the ingest tag:
#:
#:     yoru GATECRASH 4.6 / 6.3 px | omen Shrouded Step 38.5 / 40.1
#:     veto Crosscut 65.0 / 6.8    | chamber Rendezvous 323.8
#:     median 38.5 px, 1 of 8 reaching TELEPORT_PX
#:
#: and the player-reviewed Lotus Omen relocation is ~52 px. So a real teleport
#: is usually SHORT, and a rule of "far enough to be a teleport" refuses the
#: events it exists to admit while admitting phantoms, which sit at exactly
#: these distances too (`jump_census.py`: 54.7% of refused steps are at
#: "teleport distance"). Distance cannot separate the two and no re-fit of
#: this number will change that -- **corroboration can**, which is what
#: `Corroboration` below is for. This constant survives only as the fallback
#: for a caller with no event channel, and every step it admits is reported
#: `TELEPORT_ASSUMED` so the assumption is countable rather than invisible.
TELEPORT_PX = 200.0

#: Per-observation centre error of an icon fit, widget px at scale 1.0.
#:
#: **Measured from FORCED CORRESPONDENCES**, which need no tracker and no
#: labels: in the 2 s 60 Hz Ascent and Lotus windows the self icon is detected
#: in every one of the 120 frames, exactly once, so consecutive detections are
#: the same entity by construction. Physical motion can contribute at most
#: `RUN_PX * 1/60 = 0.75 px` at that rate, so the rest of each step is fit
#: error, whatever the player was doing:
#:
#:     residual after the walk allowance, 238 self pairs over the two maps
#:     p50 0.25 / -0.75   p90 1.49 / 2.08   p99 2.86 / 3.25   max 3.25 / 3.72
#:
#: An independent measurement agrees on the magnitude: `prototypes/CLAUDE.md`
#: recorded the fitted centre moving 1.0 px per frame on stable frames and 3.2
#: on flip frames (p90 5.0 and 8.5) at 15 Hz -- taken to diagnose the bearing
#: flip, with nothing to do with association.
#:
#: 2.0 px is not knife-edge: every value from 2.0 to 10.0 holds the self track
#: at ONE id across both windows, and the ceiling is icon separation -- two
#: icons closer than ~2r = 20 px are not separately detectable anyway, so 2e
#: spends 4 of a 20 px budget. Below 2.0 the track fragments: at the old
#: sqrt(0.5) (quantization only, which is a floor rather than a measurement)
#: the same 120 frames became 13 and 10 ids.
FIT_ERR_PX = 2.0


@dataclass(frozen=True)
class Motion:
    """What a class of entity may do between two observations.

    `max_px_s` is None for "does not translate at all" -- which is a real
    value, not a missing one. A Cypher cam has it; so does an X mark.
    """

    name: str
    max_px_s: float | None          # None: never translates
    may_dash: bool = False          # brief excursion up to DASH_PX_S
    may_teleport: bool = False      # a legal discontinuity, any distance
    rotates: bool = False           # bearing may change with origin fixed
    lifetime_s: float | None = None  # hard expiry, seconds
    note: str = ""


#: The classes, and the fact each rests on. Extend this rather than adding a
#: branch anywhere else: the whole design is that behaviour lives in the table.
CLASSES: dict[str, Motion] = {
    # Anything a person walks. The ceiling is the measured one.
    "walker": Motion("walker", RUN_PX,
                     note="a player on foot; RUN_PX is measured"),
    # Jett, Neon, Waylay. Continuous, but over the gate at a 15 Hz sample.
    "walker_dash": Motion("walker_dash", RUN_PX, may_dash=True,
                          note="Jett, Neon, Waylay Q -- and Waylay's first "
                               "dash can go UPWARD, which the minimap cannot "
                               "show at all"),
    # Omen x2, Chamber, Veto, Waylay E, Yoru E. A jump here is CORRECT.
    "walker_teleport": Motion("walker_teleport", RUN_PX, may_teleport=True,
                              note="Omen x2, Chamber, Veto, Waylay E, Yoru E"),
    # Sova drone, Fade prowler, Skye dog and birds, Tejo drone. Motion is
    # representative in the demo corpus because the player flew them deliberately.
    "piloted": Motion("piloted", RUN_PX, rotates=True,
                      note="scouts under player control; translate AND rotate"),
    # Cypher cam. Rotation is shown by the glyph turning INSIDE the ring, and
    # it has no lobe -- so rotation cannot reject a cam, only translation can.
    "fixed_rotator": Motion("fixed_rotator", None, rotates=True,
                            note="Cypher cam -- perfect circle, never translates"),
    # X marks, question marks, deployed devices, walls, smokes.
    "static": Motion("static", None,
                     note="a mark or a placed device; a moving one is a "
                          "mis-association, not a moving object"),
    # Omen's smoke: the ONLY known counterexample to the translation
    # invariant. It moves once, during deploy, and then never again.
    "settles": Motion("settles", RUN_PX,
                      note="Omen smoke -- translates while deploying, then "
                           "stops forever; a track that keeps moving is a "
                           "player, one that stops is a smoke"),
    # Killjoy's alarmbot (origin-driven) and turret (bearing-driven). Slow, and
    # the motion is itself an ENEMY DETECTION -- see the doc's §3.
    "enemy_reactive": Motion("enemy_reactive", RUN_PX, rotates=True,
                             note="KJ alarmbot moves toward an enemy; her "
                                  "turret snaps onto one"),
}
#: Pings are static with a hard expiry, one class per glyph so the lifetime is
#: the one measured for that glyph rather than an average over them.
for _k, _s in LIFETIME_S.items():
    CLASSES[f"ping_{_k}"] = Motion(f"ping_{_k}", None, lifetime_s=_s,
                                   note="a ping does not move and does not "
                                        "expand; it is full size in under one "
                                        "frame and then sits for its lifetime")

#: A step admitted only because a class MAY dash. Reported separately because
#: `DASH_PX_S` is a bound rather than a measurement -- see its note.
WEAK = "weak"

#: A step admitted only by `TELEPORT_PX`, with no event corroborating it.
#: Reported separately for the same reason as `WEAK`, and it is the weaker of
#: the two: the distance rule is known to refuse most real teleports and to
#: admit phantoms at the same distances. Count these; do not trust them.
TELEPORT_ASSUMED = "teleport_assumed"

#: What a corroborated teleport needs, and why each half is required.
#:
#: **Audio alone describes a FAKE teleport** -- Yoru's whole ability is the
#: sound without the traversal -- so a cast or a sound is a licence to look,
#: never a finding. The icon must actually be somewhere else AND the viewcone
#: must have gone with it; a relocated icon whose cone stayed put is an
#: association error, not a player.
TELEPORT_RELOCATION = frozenset({"icon", "viewcone"})
#: ...and one channel that ties the relocation to THIS entity rather than to
#: some entity having moved: the sound (identity by testimony) or an observed
#: source/destination link.
TELEPORT_LINK = frozenset({"audio", "destination"})


@dataclass(frozen=True)
class Corroboration:
    """The evidence licensing ONE discontinuity, from channels outside motion.

    This is the thing `TELEPORT_PX` was standing in for, and the substitution
    is the point: *how far did it jump* is not evidence about whether a jump
    happened, because real teleports are short and phantoms are long. *What
    else saw it* is.

    `channels` names the channels that observed the relocation. `predecessor`
    is the entity the destination continues -- required, because a teleport is
    a RELOCATION of a known entity and a jump with no origin is a birth, which
    is a different claim needing different evidence (`minimap_lifecycle`).
    `refs` carries the source evidence; a corroboration with none is inert.
    """

    channels: frozenset[str] = frozenset()
    predecessor: str | None = None
    refs: tuple = ()

    @classmethod
    def of(cls, event: dict) -> "Corroboration":
        """Read one stored origin event. Absent fields stay absent, not false."""
        return cls(frozenset(event.get("channels") or ()),
                   event.get("predecessor"),
                   tuple(event.get("evidence_refs") or ()))


def corroborates_teleport(ev: Corroboration) -> tuple[bool, str]:
    """Does this evidence license a relocation? `(ok, why)`, why names the gap.

    One rule, in one place, so the tracker's admissibility and the lifecycle's
    origin adjudication cannot drift apart -- they were separately written and
    the second is what the first should have been asking all along.
    """
    if not ev.refs:
        return (False, "no source evidence")
    if ev.predecessor is None:
        return (False, "no predecessor entity: a jump with no origin is a birth")
    missing = TELEPORT_RELOCATION - ev.channels
    if missing:
        return (False, "relocation unobserved: " + ", ".join(sorted(missing)))
    if not (ev.channels & TELEPORT_LINK):
        return (False, "relocation not linked to this entity: "
                       "needs " + " or ".join(sorted(TELEPORT_LINK)))
    return (True, "teleport corroborated by " + ", ".join(sorted(ev.channels)))


def admits(motion: Motion, dist_px: float, dt_s: float, scale: float = 1.0,
           age_s: float | None = None,
           evidence: "Corroboration | None" = None) -> tuple[bool, str]:
    """May an entity of this class have moved `dist_px` in `dt_s`?

    Returns `(ok, why)`. `why` names the rule that decided, so a rejection can
    be read back -- a tracker that says no without saying which law was broken
    cannot be debugged, and this repo has paid for silent rejections before.

    `scale` is the widget scale, because every distance here is in WIDGET
    pixels and the widget has two sizes.

    **`evidence` is how a discontinuity gets licensed.** Pass the corroboration
    for a relocation at this step and any distance above the walk ceiling is
    admissible -- `TELEPORT_PX` is not consulted at all, which is the whole
    change: the measured teleports are 4.6 to 65 px and the reviewed Lotus one
    is ~52, so the distance rule was refusing them. With no evidence the
    fallback still admits a jump past `TELEPORT_PX`, marked `TELEPORT_ASSUMED`
    so a caller can count what rests on the assumption and refuse it.
    """
    if dt_s <= 0:
        return (dist_px == 0, "zero interval")
    if motion.lifetime_s is not None and age_s is not None \
            and age_s > motion.lifetime_s:
        return (False, f"past its {motion.lifetime_s:g}s lifetime")
    if motion.max_px_s is None:
        # Not a speed of zero -- a statement that translation is not a thing
        # this class does. Sub-pixel jitter is detection noise, not motion.
        return (dist_px <= 1.5 * scale, "does not translate")
    walk = motion.max_px_s * scale * dt_s
    if dist_px <= walk:
        return (True, "within walking distance")
    if motion.may_dash and dist_px <= DASH_PX_S * scale * dt_s:
        return (True, WEAK)
    if motion.may_teleport and evidence is not None:
        ok, why = corroborates_teleport(evidence)
        if ok:
            return (True, why)
        # Insufficient evidence is not a veto -- the distance fallback below
        # still gets its say -- but the gap in it is what gets reported.
        if dist_px < TELEPORT_PX * scale:
            return (False, why)
    if motion.may_teleport and dist_px >= TELEPORT_PX * scale:
        return (True, TELEPORT_ASSUMED)
    if motion.may_teleport:
        return (False, "too far to walk, too near to be a teleport")
    return (False, f"exceeds {motion.max_px_s:g} px/s")


def association_tolerance(scale: float = 1.0,
                          position_error_px: float = FIT_ERR_PX,
                          r_a: float | None = None,
                          r_b: float | None = None) -> float:
    """How far two centres may differ WITHOUT the entity having moved.

    Detector error, not motion -- so it is added to whatever `admits` allows
    rather than folded into a speed. Two terms, and neither is a knob:

    * `2 * position_error_px * scale` -- the fit's own centre error at both
      endpoints, measured (`FIT_ERR_PX`);
    * `|r_a - r_b| * scale` -- **derived, not fitted.** An arc fit places the
      centre at `p + r*n` for an arc point `p` and its inward normal, so two
      fits that share an arc point and disagree about the radius by dr
      necessarily disagree about the centre by dr. The detector is reporting
      its own uncertainty here and it is free.

    It shows in the data. Over the forced pairs in the Ascent window the
    largest step by radius disagreement is 2.0 px at dr=0, 5.4 at dr=2 and
    9.2 at dr=4 -- the icon is not accelerating, the fit is sliding.

    One definition, because there were three: this, the tracker's own
    subtraction, and `minimap_lifecycle`'s `sqrt(2)` continuation ceiling,
    which disagreed by a factor of three and quarantined observations the
    tracker had already associated.
    """
    slack = 2.0 * position_error_px * scale
    if r_a is not None and r_b is not None:
        slack += abs(float(r_a) - float(r_b)) * scale
    return slack


def is_teleport(why: str) -> bool:
    """Did `admits` decide by a discontinuity rule? Corroborated or assumed.

    A caller needs this to know it must NOT interpolate across the step -- a
    legal discontinuity has no route through it to draw. The two reasons are
    kept apart in the string because they are not equally trustworthy, and
    joined here because the no-interpolation consequence is the same.
    """
    return why == TELEPORT_ASSUMED or why.startswith("teleport corroborated")


def explain(dist_px: float, dt_s: float, scale: float = 1.0) -> dict[str, str]:
    """Which classes admit this step, and by which rule. The falsifier.

    This is the shape the whole module is for. It never returns an identity --
    it returns the SET an observation is consistent with, which shrinks as
    other evidence arrives and is the honest thing to carry until it does.
    """
    out = {}
    for name, m in CLASSES.items():
        ok, why = admits(m, dist_px, dt_s, scale)
        if ok:
            out[name] = why
    return out


def assign(cost: list[list[float]], forbidden: float = float("inf")) -> list[int]:
    """Minimum-cost one-to-one assignment. Hungarian, O(n^3), no scipy.

    Written out rather than imported because the four dependencies in
    `requirements.txt` are the whole environment and adding scipy for one
    function is not worth it at these sizes -- a frame holds at most a handful
    of tracks and a couple of dozen candidates.

    **Greedy nearest-neighbour is what this replaces, and the difference is
    the entire point.** Greedy assigns the closest pair first and then lives
    with it, so when two allies cross, the one that happens to be scored first
    takes the other's detection and both identities swap. That is precisely
    the case ally identity exists to handle. A joint optimum can pay a little
    on one pair to keep the whole assignment coherent.

    Returns, per row, the column it takes, or -1 for none. A `forbidden` cost
    (the default, infinity) means the pair is inadmissible -- which is how a
    motion law enters the assignment rather than being applied afterwards.
    """
    if not cost or not cost[0]:
        return [-1] * len(cost)
    n_r, n_c = len(cost), len(cost[0])
    n = max(n_r, n_c)
    big = 1e12
    # Square, padded with zeros so unmatched rows are free rather than forced.
    a = [[0.0] * n for _ in range(n)]
    for i in range(n_r):
        for j in range(n_c):
            c = cost[i][j]
            a[i][j] = big if (c is None or c >= forbidden or c != c) else float(c)

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1

    out = [-1] * n_r
    for j in range(1, n + 1):
        i = p[j] - 1
        if 0 <= i < n_r and j - 1 < n_c and a[i][j - 1] < big:
            out[i] = j - 1
    return out


# --------------------------------------------------------------------- tracker


@dataclass
class Track:
    """One entity followed across frames, with its last KNOWN bearing.

    `facing` and `facing_t_ms` are kept apart from the position deliberately.
    A position is interpolated over a gap because a walker's speed is bounded
    and the intervening path is constrained; **a bearing is not** -- a player
    can turn 180 degrees between two samples and nothing forbids it. So a
    carried-forward bearing is a WEAKER claim than a carried-forward position,
    it is marked as such (`facing_age_ms`), and the collective viewcone
    excludes it by default. See `Tracker.step`.
    """

    tid: int
    x: float
    y: float
    t_ms: float
    facing: float | None = None
    facing_t_ms: float | None = None
    n_obs: int = 1
    missed: int = 0
    born_t_ms: float = 0.0
    #: The radius the icon fit last reported, or None if it did not report one.
    #: Carried because it bounds how far the CENTRE can have moved without the
    #: icon having moved -- see `Tracker.tolerance`.
    r: float | None = None
    #: Recent measured bearings, `(t_ms, deg)`, newest last. The window is what
    #: makes a bearing usable at all -- see `resolved_facing`.
    history: list = field(default_factory=list)

    def facing_age_ms(self, t_ms: float) -> float | None:
        if self.facing is None or self.facing_t_ms is None:
            return None
        return t_ms - self.facing_t_ms

    def resolved_facing(self, window_ms: float = 200.0):
        """`(deg, resultant)` over the recent window, or `(None, 0.0)`.

        **The per-frame bearing is not usable on its own and this is measured.**
        At 15 Hz the change between CONSECUTIVE self bearings is bimodal: 47%
        under 10 degrees and a second mode at 150-180 degrees holding 16.1%.
        Nobody turns 180 degrees in 67 ms one time in six, so that mode is the
        fit choosing between two opposed lobes rather than the player turning
        (`prototypes/cone_flip.py`).

        The circular mean over a short window collapses it -- 16.1% to 1.2% at
        +/-2 samples -- but that measurement is partly circular, because
        smoothing a series necessarily shrinks its own frame-to-frame
        difference. **`resultant` is the part that is not**: the length of the
        mean resultant vector, 1.0 when every bearing in the window agrees and
        0.0 when they are opposed. A per-window ambiguity signal needing no
        neighbour comparison and no ground truth.

        Checked against evidence the bearing cannot see -- the direction the
        player MOVED, which comes from the ring centre rather than the lobe --
        over 453 intervals of at least 15 px in 0.53 s:

            series                    aligned <45deg   opposed >135deg   gap
            raw bearing                    45.3%            28.5%       +16.8
            smoothed +/-2                  41.7%            24.5%       +17.2
            smoothed, resultant >= 0.5     47.1%            23.9%       +23.2

        So the smoothing alone is worth almost nothing and **the gate is where
        the win is**. Neither column is an accuracy -- strafing and
        backpedalling are real -- so the GAP between them is the signal.
        """
        import math

        if not self.history:
            return None, 0.0
        t_now = self.history[-1][0]
        w = [d for tm, d in self.history if t_now - tm <= window_ms]
        if not w:
            return None, 0.0
        sx = sum(math.cos(math.radians(d)) for d in w) / len(w)
        sy = sum(math.sin(math.radians(d)) for d in w) / len(w)
        return math.degrees(math.atan2(sy, sx)), math.hypot(sx, sy)


class Tracker:
    """Identity across frames for one class of entity. Hungarian, class-gated.

    Built for ALLY ICONS, where identity cannot come from colour: the game
    draws all four teammates in one teal, so `ally_mask` is a single key and
    only motion separates them. That is exactly the case `assign`'s docstring
    was written about -- when two allies cross, greedy nearest-neighbour swaps
    their identities and a joint optimum does not.

    **The motion law enters as an INADMISSIBLE COST, not as a filter applied
    afterwards.** A pair the class cannot have done is infinite cost, so the
    assignment routes around it rather than making a match and then having it
    revoked -- which would leave the other track unmatched for no reason.

    What this is NOT: it does not decide what class an entity is. `motion` is
    supplied by the caller and the tracker answers "given that, who is who".
    Concluding the class from the behaviour is the circularity SS6 names.
    """

    def __init__(self, motion: str = "walker", scale: float = 1.0,
                 max_facing_age_ms: float = 500.0,
                 bearing_window_ms: float = 200.0, min_resultant: float = 0.5,
                 max_gap_ms: float = 500.0,
                 position_error_px: float = FIT_ERR_PX,
                 min_separation_px: float = MIN_ICON_SEPARATION_PX):
        self.motion = CLASSES[motion]
        self.scale = scale
        #: The widget cannot draw two icons closer than this, so a detection
        #: this near an unobserved track is that track's icon refit rather than
        #: a new entity -- see `step`. The SAME-FRAME half of this rule lives
        #: in `minimap.icons`, where the fits are produced; here it is the
        #: temporal half, which the detector cannot see. 0 disables it.
        self.min_separation_px = min_separation_px
        if max_gap_ms <= 0:
            raise ValueError("max_gap_ms must be positive")
        #: A track expires on ELAPSED TIME and nothing else. It used to expire
        #: on a frame count as well (`max_missed=3`), and that is the same
        #: quantity in a unit that depends on the sample rate: at the 60 Hz the
        #: contiguous windows are rendered at, three missed frames is 50 ms, so
        #: the 500 ms budget written here was never the one being applied. The
        #: frame count is gone rather than raised -- two constants for one law
        #: is how they disagree.
        self.max_gap_ms = max_gap_ms
        # Per-observation centre error. `FIT_ERR_PX` is measured from forced
        # correspondences; the old default (sqrt(0.5), integer quantization)
        # was a floor on it rather than a measurement of it, and cost 12 of 13
        # self ids on a window where the icon was never once missed.
        # This widens association only, never changes stored coordinates/speeds.
        if position_error_px < 0:
            raise ValueError("position_error_px must be nonnegative")
        self.position_error_px = position_error_px
        self._last_t_ms = None
        self.max_facing_age_ms = max_facing_age_ms
        #: The window `resolved_facing` aggregates over, and the ambiguity gate
        #: below which no bearing is offered at all. 0.5 keeps 69% of frames
        #: and takes the movement-alignment gap from +16.8 to +23.2 points --
        #: see `Track.resolved_facing`. Refusing under-claims, which is the rule.
        self.bearing_window_ms = bearing_window_ms
        self.min_resultant = min_resultant
        self.tracks: list[Track] = []
        self._next = 0

    def step(self, t_ms: float, dets: list[dict]) -> list[Track]:
        """Feed one frame's detections; returns the tracks alive after it.

        A detection is `{"cx", "cy", "facing"}` -- `minimap.icons`'s rows fit
        without translation. A `facing` of None does NOT end anything: the
        track keeps its last bearing and ages it, which is the origin-event
        model applied to one attribute (*a bad frame is a missing OBSERVATION,
        not a missing ENTITY*).
        """
        import math
        if not math.isfinite(t_ms) or (self._last_t_ms is not None
                                      and t_ms <= self._last_t_ms):
            raise ValueError("tracker timestamps must be finite and strictly increasing")
        self._last_t_ms = t_ms
        alive = [t for t in self.tracks if t_ms - t.t_ms <= self.max_gap_ms]
        cost: list[list[float]] = []
        for tr in alive:
            dt = (t_ms - tr.t_ms) / 1000.0
            row = []
            for d in dets:
                dist = float(((d["cx"] - tr.x) ** 2 + (d["cy"] - tr.y) ** 2) ** 0.5)
                slack = self.tolerance(tr, d)
                ok, _why = admits(self.motion, dist, dt, self.scale)
                if not ok and slack:
                    ok, _why = admits(self.motion, max(0.0, dist - slack),
                                      dt, self.scale)
                row.append(dist if ok else float("inf"))
            cost.append(row)

        taken = set()
        if alive and dets:
            for i, j in enumerate(assign(cost)):
                if j < 0 or cost[i][j] == float("inf"):
                    continue
                tr, d = alive[i], dets[j]
                tr.x, tr.y, tr.t_ms = d["cx"], d["cy"], t_ms
                tr.r = d.get("r", tr.r)
                tr.n_obs += 1
                tr.missed = 0
                if d.get("facing") is not None:
                    tr.facing, tr.facing_t_ms = d["facing"], t_ms
                    tr.history.append((t_ms, float(d["facing"])))
                    tr.history[:] = [h for h in tr.history
                                     if t_ms - h[0] <= self.bearing_window_ms]
                taken.add(j)

        for tr in alive:
            if tr.t_ms != t_ms:
                tr.missed += 1

        for j, d in enumerate(dets):
            if j in taken:
                continue
            # **The resolution limit overrides the motion law here.** A
            # detection this close to a track the widget did not draw a second
            # icon beside is the SAME icon, refit -- the motion law says a
            # walker cannot cross 8 px in 17 ms and it is right, but nothing
            # crossed: the fit moved. Minting an identity instead is what made
            # one Ascent ally alternate between two of them. Only an
            # unobserved track is eligible, so this never steals a detection
            # from an entity that has one of its own this frame.
            limit = self.min_separation_px * self.scale
            near = [t for t in alive if t.t_ms != t_ms
                    and ((d["cx"] - t.x) ** 2 + (d["cy"] - t.y) ** 2) ** 0.5 <= limit]
            if limit and near:
                tr = min(near, key=lambda t: (d["cx"] - t.x) ** 2 + (d["cy"] - t.y) ** 2)
                tr.x, tr.y, tr.t_ms = d["cx"], d["cy"], t_ms
                tr.r = d.get("r", tr.r)
                tr.n_obs += 1
                tr.missed = 0
                if d.get("facing") is not None:
                    tr.facing, tr.facing_t_ms = d["facing"], t_ms
                    tr.history.append((t_ms, float(d["facing"])))
                    tr.history[:] = [h for h in tr.history
                                     if t_ms - h[0] <= self.bearing_window_ms]
                continue
            self._next += 1
            alive.append(Track(
                tid=self._next, x=d["cx"], y=d["cy"], t_ms=t_ms, r=d.get("r"),
                facing=d.get("facing"),
                facing_t_ms=t_ms if d.get("facing") is not None else None,
                born_t_ms=t_ms,
                history=([(t_ms, float(d["facing"]))]
                         if d.get("facing") is not None else [])))

        # Everything in `alive` passed the elapsed-gap test at the top of this
        # step and nothing has aged since, so there is no second sweep here.
        # `missed` is still counted -- it is a useful diagnostic -- but it no
        # longer decides anything.
        self.tracks = alive
        return list(self.tracks)

    def tolerance(self, track: "Track", det: dict) -> float:
        """This tracker's `association_tolerance` for one track/detection pair."""
        return association_tolerance(self.scale, self.position_error_px,
                                     track.r, det.get("r"))

    def principal(self) -> "Track | None":
        """The best-supported track, for a role the game draws AT MOST ONE of.

        The self icon is the case: there is exactly one, so two live tracks are
        one real icon and one mistake, and which is which is a question about
        evidence rather than about this frame. `n_obs` is that evidence.

        **What this replaces is a per-frame choice made on `cov` alone.** The
        overlay used to take the highest-coverage self candidate each frame,
        before the tracker saw any of them, so a self-coloured blob that scored
        better for one frame moved the player across the map and back: in the
        Haven death window the reported self position alternated between two
        points 35-45 px apart, seven times in three seconds, on candidates
        whose `cov` sat at the 0.25 floor. The track already knows which one
        cannot have happened -- asking it is cheaper and more honest than
        tuning a coverage threshold.

        Ties (a fresh window, where every track has one observation) fall to
        the most recently observed, then to the oldest id, so the choice is
        deterministic rather than dictionary order.
        """
        if not self.tracks:
            return None
        return max(self.tracks, key=lambda t: (t.n_obs, t.t_ms, -t.tid))

    def bearings(self, t_ms: float, allow_interpolated: bool = False,
                 tracks: "list[Track] | None" = None):
        """`(x, y, facing_or_None, interpolated)` per track, for the cone.

        The bearing is `Track.resolved_facing` -- a windowed circular mean,
        REFUSED below `min_resultant` -- not the last per-frame fit, because
        the per-frame fit flips 180 degrees on 16% of frames and no threshold
        on `cov` or `lobe` can see it (a flip scores a HIGHER median lobe).

        **A carried bearing is still refused by default.** The error of
        carrying one forward has a p90 of ~160 degrees against a null of 160 at
        EVERY gap from 67 ms to 3 s -- flat, so it is not the player turning
        and raising the sample rate does not help. `allow_interpolated=True`
        exists to measure what the carry is worth, never to widen the
        observable area before that measurement exists: an area that is too
        large silently discards real enemy observations, while one that is too
        small only fails to fire.
        """
        out = []
        for tr in (self.tracks if tracks is None else tracks):
            deg, res = tr.resolved_facing(self.bearing_window_ms)
            fresh = (tr.facing_t_ms is not None
                     and abs(t_ms - tr.facing_t_ms) <= 1e-9)
            if deg is not None and res >= self.min_resultant and fresh:
                out.append((tr.x, tr.y, deg, False))
                continue
            age = tr.facing_age_ms(t_ms)
            if (allow_interpolated and deg is not None
                    and res >= self.min_resultant
                    and age is not None and age <= self.max_facing_age_ms):
                out.append((tr.x, tr.y, deg, True))
            else:
                out.append((tr.x, tr.y, None, False))
        return out


def _self_test() -> int:
    ok = True

    def check(label, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {label}: got {got!r}, want {want!r}")
        else:
            print(f"  ok   {label}: {got}")

    W = CLASSES["walker"]
    # 45 px/s for 1 s: 40 px is a walk, 60 px is not.
    check("walker admits a walk", admits(W, 40, 1.0)[0], True)
    check("walker refuses 60 px in 1 s", admits(W, 60, 1.0)[0], False)
    # The same step at half the widget size is half the allowance.
    check("the ceiling scales with the widget",
          admits(W, 40, 1.0, scale=0.5)[0], False)

    # A cam does not translate, and that is not a speed of zero.
    C = CLASSES["fixed_rotator"]
    check("cam admits jitter", admits(C, 1.0, 1.0)[0], True)
    check("cam refuses a real move", admits(C, 8.0, 1.0)[0], False)

    # A teleport is legal for the class that has one. With no evidence the
    # only rule left is the distance bound, and it is reported as an
    # assumption rather than as a finding.
    T = CLASSES["walker_teleport"]
    check("an uncorroborated jump is ADMITTED BUT MARKED",
          admits(T, 300, 0.2), (True, TELEPORT_ASSUMED))
    check("teleport agent still refuses a mid-range step",
          admits(T, 90, 0.2)[0], False)
    check("non-teleport agent refuses that jump", admits(W, 300, 0.2)[0], False)

    # ---- evidence, not distance -----------------------------------------
    # The reviewed Lotus Omen relocation: ~52 px, which the distance rule
    # refuses ("too far to walk, too near to be a teleport") and which the
    # corroboration admits. This is the case the change exists for.
    lotus = Corroboration(frozenset({"icon", "viewcone", "audio", "destination"}),
                          predecessor="ally:1", refs=("source frames 299.217-299.317s",))
    check("52 px is refused on distance alone", admits(T, 52, 0.0167)[0], False)
    check("...and admitted when four channels corroborate it",
          admits(T, 52, 0.0167, evidence=lotus)[0], True)
    check("...naming the channels rather than a threshold",
          admits(T, 52, 0.0167, evidence=lotus)[1].startswith("teleport corroborated"), True)
    # A 4.6 px Yoru GATECRASH is inside the walk ceiling and needs no exception.
    check("a short teleport never reaches the rule at all",
          admits(T, 2.0, 0.2)[1], "within walking distance")

    # Each half of the rule is load-bearing, and each refusal says which.
    check("audio alone is a FAKE teleport, not a relocation",
          corroborates_teleport(Corroboration(frozenset({"audio"}),
                                              "ally:1", ("ref",)))[0], False)
    check("an icon that moved without its cone is an association error",
          corroborates_teleport(Corroboration(frozenset({"icon", "audio"}),
                                              "ally:1", ("ref",)))[0], False)
    check("a relocation nothing ties to an entity is not one",
          corroborates_teleport(Corroboration(frozenset({"icon", "viewcone"}),
                                              "ally:1", ("ref",)))[0], False)
    check("a jump with no origin is a BIRTH, which is a different claim",
          corroborates_teleport(Corroboration(
              frozenset({"icon", "viewcone", "audio"}), None, ("ref",)))[1],
          "no predecessor entity: a jump with no origin is a birth")
    check("evidence with no source reference is inert",
          corroborates_teleport(Corroboration(
              frozenset({"icon", "viewcone", "audio"}), "ally:1", ()))[0], False)
    # Insufficient evidence does not veto the fallback -- it reports the gap.
    thin = Corroboration(frozenset({"icon"}), "ally:1", ("ref",))
    check("thin evidence still leaves the distance fallback its say",
          admits(T, 300, 0.2, evidence=thin), (True, TELEPORT_ASSUMED))
    check("...and below the bound the gap is what gets reported",
          admits(T, 52, 0.0167, evidence=thin)[1].startswith("relocation unobserved"), True)
    check("a non-teleporting class is not licensed by any evidence",
          admits(W, 52, 0.0167, evidence=lotus)[0], False)

    # A dash is admitted, but WEAKLY, because DASH_PX_S is a bound.
    D = CLASSES["walker_dash"]
    check("dash admits, weakly", admits(D, 60, 0.5)[1], WEAK)
    check("walker refuses the same step", admits(W, 60, 0.5)[0], False)

    # A ping expires. Past its lifetime nothing may match it.
    P = CLASSES["ping_danger"]
    check("ping lives 10.0s", admits(P, 0.0, 0.1, age_s=9.0)[0], True)
    check("ping expires", admits(P, 0.0, 0.1, age_s=11.0)[0], False)
    check("standard ping expires sooner",
          admits(CLASSES["ping_standard"], 0.0, 0.1, age_s=8.0)[0], False)

    # `explain` narrows rather than decides.
    e = explain(300, 0.2)
    check("a 300 px jump is explained only by a teleport", sorted(e), ["walker_teleport"])
    e2 = explain(2.0, 0.2)
    check("a tiny step is consistent with many classes", len(e2) > 5, True)

    # Assignment: the crossing case greedy gets wrong.
    #   track A is at 0, track B at 10; detections at 10 and 0 (they crossed).
    #   Greedy takes A->10 (cost 10) then B->0 (cost 10) = 20, same as the
    #   swap here, so use a case where greedy is strictly worse:
    #   costs  A: [1, 2]   B: [1, 100]
    #   greedy picks A->0 (1) then B->1 (100) = 101; optimal is A->1, B->0 = 3.
    r = assign([[1.0, 2.0], [1.0, 100.0]])
    check("assignment beats greedy on the crossing case", r, [1, 0])
    # An inadmissible pair is not taken.
    r2 = assign([[float("inf"), 5.0], [5.0, float("inf")]])
    check("inadmissible pairs are refused", r2, [1, 0])
    # More detections than tracks.
    r3 = assign([[3.0, 1.0, 9.0]])
    check("extra detections are left unmatched", r3, [1])

    # `minimap.filter_track` taking a class. Imported here rather than at the
    # top because `minimap` is what this module imports RUN_PX from.
    from .minimap import MIN_ICON_SEPARATION_PX, RUN_PX as _RP, filter_track

    step = 100.0                       # 10 Hz
    walk = _RP * 0.1 * 0.5             # comfortably inside one step
    #   0 -> 1 walk -> a 300 px jump -> 1 walk. Four observations, one of which
    #   is only legal for a teleporting agent.
    jump = [(0.0, 0.0, 0.0), (100.0, walk, 0.0),
            (200.0, walk + 300.0, 0.0), (300.0, walk + 300.0 + walk, 0.0)]
    check("default gate drops the jump and everything after it is a new run",
          len(filter_track(jump, step)), 2)
    check("walker_teleport keeps all four",
          len(filter_track(jump, step, motion="walker_teleport")), 4)
    check("walker refuses the jump like the default",
          len(filter_track(jump, step, motion="walker")), 2)
    try:
        filter_track(jump, step, motion="not_a_class")
        raised = False
    except KeyError:
        raised = True
    check("an unknown class name raises, rather than silently walking", raised, True)

    # A teleport must NOT be interpolated across: it is a legal discontinuity,
    # and a path drawn through it is an invented one.
    gapped = [(0.0, 0.0, 0.0), (500.0, 300.0, 0.0)]
    check("a walkable gap IS interpolated",
          len(filter_track([(0.0, 0.0, 0.0), (500.0, walk, 0.0)], step,
                           motion="walker_teleport")) > 2, True)
    check("a teleport gap is NOT interpolated",
          len(filter_track(gapped, step, motion="walker_teleport")), 2)

    # A SPAN list applies a class only inside it. The jump sits at t=200 ms,
    # so a span covering it keeps all four and a span missing it does not.
    check("a span containing the jump keeps it",
          len(filter_track(jump, step,
                           motion=[(150.0, 250.0, "walker_teleport")])), 4)
    check("a span elsewhere does not",
          len(filter_track(jump, step,
                           motion=[(900.0, 1000.0, "walker_teleport")])), 2)
    check("an empty span list is the default gate",
          len(filter_track(jump, step, motion=[])), 2)

    # ---- the short teleport, end to end --------------------------------
    # The Lotus shape: ~52 px at 60 Hz, which every distance rule refuses.
    # A span alone does not save it; the span PLUS the corroboration does.
    short = [(0.0, 0.0, 0.0), (16.7, 0.0, 0.0), (33.4, 52.0, 0.0), (50.1, 52.0, 0.0)]
    check("a class alone still loses a 52 px relocation",
          len(filter_track(short, 16.7, motion="walker_teleport")), 2)
    check("...and the corroborated span keeps it whole",
          len(filter_track(short, 16.7,
                           motion=[(0.0, 100.0, "walker_teleport", lotus)])), 4)
    check("...without inventing a route through it",
          [round(x, 1) for _t, x, _y in
           filter_track(short, 16.7,
                        motion=[(0.0, 100.0, "walker_teleport", lotus)])],
          [0.0, 0.0, 52.0, 52.0])
    # A stored origin event is accepted where a Corroboration is.
    check("a stored event row is read as evidence",
          len(filter_track(short, 16.7, motion=[(0.0, 100.0, "walker_teleport", {
              "channels": ["icon", "viewcone", "audio"], "predecessor": "ally:1",
              "evidence_refs": ["source frames"]})])), 4)

    # The default path is untouched by any of this.
    check("default still interpolates a walkable gap",
          len(filter_track([(0.0, 0.0, 0.0), (500.0, walk, 0.0)], step)) > 2, True)

    # ---- Tracker: identity across frames, and the bearing carry ----------
    tk = Tracker("walker", scale=1.0, max_facing_age_ms=500.0)
    #   two allies approaching each other, then crossing. Greedy swaps them.
    #   They start further apart than `MIN_ICON_SEPARATION_PX`, because closer
    #   than that the widget draws one overlapping blob -- see `resolve`.
    tk.step(0.0, [{"cx": 0.0, "cy": 0.0, "facing": 0.0},
                  {"cx": 40.0, "cy": 0.0, "facing": 180.0}])
    ids0 = sorted(t.tid for t in tk.tracks)
    check("two detections make two tracks", len(ids0), 2)
    tk.step(100.0, [{"cx": 4.0, "cy": 0.0, "facing": 0.0},
                    {"cx": 36.0, "cy": 0.0, "facing": 180.0}])
    check("and they keep their ids through the approach",
          sorted(t.tid for t in tk.tracks), ids0)
    #   the one that started at 0 is now the one further right.
    by_id = {t.tid: t for t in tk.tracks}
    check("the assignment is coherent, not greedy-swapped",
          by_id[ids0[0]].x < by_id[ids0[1]].x, True)

    # A step no walker could take starts a NEW track rather than teleporting.
    tk2 = Tracker("walker", scale=1.0)
    tk2.step(0.0, [{"cx": 0.0, "cy": 0.0, "facing": 0.0}])
    first = tk2.tracks[0].tid
    tk2.step(100.0, [{"cx": 300.0, "cy": 0.0, "facing": 0.0}])
    check("an inadmissible step is a new identity, not a jump",
          any(t.tid != first for t in tk2.tracks), True)
    #   ...and for an agent that MAY teleport, it is the same identity.
    tk3 = Tracker("walker_teleport", scale=1.0)
    tk3.step(0.0, [{"cx": 0.0, "cy": 0.0, "facing": 0.0}])
    f3 = tk3.tracks[0].tid
    tk3.step(100.0, [{"cx": 300.0, "cy": 0.0, "facing": 0.0}])
    check("a teleport agent keeps its identity across the jump",
          [t.tid for t in tk3.tracks], [f3])

    # The bearing carry, and the refusal that is the whole point.
    tk4 = Tracker("walker", scale=1.0, max_facing_age_ms=500.0)
    tk4.step(0.0, [{"cx": 0.0, "cy": 0.0, "facing": 45.0}])
    check("a fresh bearing is offered", tk4.bearings(0.0)[0][2], 45.0)
    tk4.step(100.0, [{"cx": 2.0, "cy": 0.0, "facing": None}])
    check("a refused bearing is NOT offered by default",
          tk4.bearings(100.0)[0][2], None)
    check("but the track still knows it, and says it is carried",
          tk4.bearings(100.0, allow_interpolated=True)[0][2:], (45.0, True))
    check("the position is not lost with the bearing",
          tk4.bearings(100.0)[0][0], 2.0)
    tk4.step(1000.0, [{"cx": 4.0, "cy": 0.0, "facing": None}])
    check("and the carry expires past max_facing_age_ms",
          tk4.bearings(1000.0, allow_interpolated=True)[0][2], None)

    # A track is dropped on ELAPSED TIME, and only on that. The frame count
    # this used to also expire on made the real budget depend on the sample
    # rate -- three missed frames is 50 ms at 60 Hz and 200 ms at 15 Hz -- so
    # the same track survived a blink at one rate and not at the other.
    tk5 = Tracker("walker", scale=1.0, max_gap_ms=250.0)
    tk5.step(0.0, [{"cx": 0.0, "cy": 0.0, "facing": 0.0}])
    for t_ms in (16.7, 33.4, 50.1, 66.8, 83.5, 100.2):
        tk5.step(t_ms, [])
    check("six missed frames inside the budget do not drop it",
          len(tk5.tracks), 1)
    check("...and the track is still associable when the icon returns",
          tk5.step(117.0, [{"cx": 2.0, "cy": 0.0, "facing": 0.0}])[0].tid,
          tk5.tracks[0].tid)
    tk5.step(400.0, [])
    check("past the elapsed budget it is dropped", len(tk5.tracks), 0)

    # ---- two fits of one icon are not two entities ----------------------
    # The Ascent signature: a stable r=8 fit with a second r=12-13 fit about
    # 8 px away, arriving ONE AT A TIME on alternating frames -- which is the
    # half `minimap.icons` cannot see, because it never sees two frames.
    pair = [{"cx": 141.0, "cy": 133.0, "r": 8, "cov": 0.46, "facing": 0.0},
            {"cx": 134.0, "cy": 130.0, "r": 12, "cov": 0.27, "facing": 0.0}]
    tka = Tracker("walker", scale=1.0)
    tka.step(0.0, [pair[0]])
    for k in range(1, 8):
        tka.step(k * 16.7, [pair[k % 2]])
    check("an alternating fit is one identity, not two", len(tka.tracks), 1)
    check("...and a fit 45 px away is still a second one",
          len(tka.step(8 * 16.7, [pair[0], dict(pair[1], cx=186.0, cy=133.0)])), 2)

    # The radius the fit reported bounds how far its centre may have slid.
    # `min_separation_px=0` isolates the tolerance: inside the resolution limit
    # the rule above would absorb these steps whatever the tolerance said.
    tk8 = Tracker("walker", scale=1.0, position_error_px=0.0, min_separation_px=0)
    tk8.step(0.0, [{"cx": 0.0, "cy": 0.0, "r": 8, "facing": None}])
    first = tk8.tracks[0].tid
    check("a 4 px step at 60 Hz is not a walk",
          admits(W, 4.0, 1 / 60.0)[0], False)
    check("...and with no radius disagreement it breaks the track",
          tk8.step(16.7, [{"cx": 4.0, "cy": 0.0, "r": 8, "facing": None}])[-1].tid != first,
          True)
    tk9 = Tracker("walker", scale=1.0, position_error_px=0.0, min_separation_px=0)
    tk9.step(0.0, [{"cx": 0.0, "cy": 0.0, "r": 8, "facing": None}])
    check("...while a fit that also moved its radius by 4 px keeps it",
          tk9.step(16.7, [{"cx": 4.0, "cy": 0.0, "r": 12, "facing": None}])[0].tid,
          tk9.tracks[0].tid)

    # ---- the ambiguity gate: the fix for the 180-degree flip --------------
    tk6 = Tracker("walker", scale=1.0, bearing_window_ms=300.0, min_resultant=0.5)
    for k, deg in enumerate((40.0, 44.0, 42.0, 41.0)):
        tk6.step(k * 67.0, [{"cx": k * 0.5, "cy": 0.0, "facing": deg}])
    deg, res = tk6.tracks[0].resolved_facing(300.0)
    check("an agreeing window resolves near its members", 38 < deg < 46, True)
    check("and its resultant is near 1", res > 0.99, True)
    check("so a bearing is offered", tk6.bearings(3 * 67.0)[0][2] is not None, True)

    #   the flip case: bearings alternating 180 degrees apart. The circular
    #   MEAN of opposed vectors is meaningless, and `resultant` is what says so.
    tk7 = Tracker("walker", scale=1.0, bearing_window_ms=300.0, min_resultant=0.5)
    for k, deg in enumerate((0.0, 180.0, 0.0, 180.0)):
        tk7.step(k * 67.0, [{"cx": k * 0.5, "cy": 0.0, "facing": deg}])
    _d, res7 = tk7.tracks[0].resolved_facing(300.0)
    check("opposed bearings give a near-zero resultant", res7 < 0.2, True)
    check("so NO bearing is offered -- the refusal is the fix",
          tk7.bearings(3 * 67.0)[0][2], None)

    #   ONE flip in a five-sample window is outvoted; TWO are refused. The
    #   arithmetic is exact and worth asserting, because it is what the default
    #   window and gate buy: with n agreeing and m opposed the resultant is
    #   (n - m) / (n + m), so 4-vs-1 gives 0.6 and 3-vs-2 gives 0.2.
    def five(degs, thr=0.5):
        tk = Tracker("walker", scale=1.0, bearing_window_ms=400.0,
                     min_resultant=thr)
        for k, deg in enumerate(degs):
            tk.step(k * 67.0, [{"cx": k * 0.5, "cy": 0.0, "facing": deg}])
        return tk, tk.tracks[0].resolved_facing(400.0)

    tk8, (d8, r8) = five((90.0, 92.0, -88.0, 91.0, 90.0))
    check("one flip in five is outvoted", 80 < d8 < 100, True)
    check("and the window still clears the gate", round(r8, 2), 0.6)
    check("so a bearing is still offered",
          tk8.bearings(4 * 67.0)[0][2] is not None, True)

    tk10, (_d10, r10) = five((90.0, -88.0, 91.0, -90.0, 90.0))
    check("two flips in five is refused", round(r10, 2), 0.2)
    check("and no bearing is offered", tk10.bearings(4 * 67.0)[0][2], None)

    #   the gate is a real gate: raise it and the tolerated window is refused.
    tk9, _ = five((90.0, 92.0, -88.0, 91.0, 90.0), thr=0.95)
    check("a stricter gate refuses even one flip",
          tk9.bearings(4 * 67.0)[0][2], None)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    print(f"{len(CLASSES)} motion classes, RUN_PX={RUN_PX:g} widget px/s\n")
    print(f"{'class':<20}{'max px/s':>10}{'dash':>6}{'tele':>6}{'rot':>5}"
          f"{'life':>7}")
    for name, m in CLASSES.items():
        print(f"{name:<20}{'--' if m.max_px_s is None else f'{m.max_px_s:g}':>10}"
              f"{'y' if m.may_dash else '':>6}{'y' if m.may_teleport else '':>6}"
              f"{'y' if m.rotates else '':>5}"
              f"{'--' if m.lifetime_s is None else f'{m.lifetime_s:g}s':>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
