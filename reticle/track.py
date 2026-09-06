r"""Identity-conditional tracking: what a track is ALLOWED to do next.

    python -m reticle.track --self-test

the player, 2026-09-06, giving the direction for the minimap entity model:

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
from dataclasses import dataclass

#: Top speed of a real track, widget px/s. `minimap.RUN_PX`, measured rather
#: than derived -- every filtered track sits under it and every misdetection
#: blew far past it. Imported rather than restated so there is one definition.
from .minimap import RUN_PX

#: Ping lifetimes, seconds. `ping.LIFETIME_S`, exact to 0.1 s at a 10 Hz
#: sample. Imported for the same reason.
from .ping import LIFETIME_S

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
TELEPORT_PX = 200.0


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


def admits(motion: Motion, dist_px: float, dt_s: float, scale: float = 1.0,
           age_s: float | None = None) -> tuple[bool, str]:
    """May an entity of this class have moved `dist_px` in `dt_s`?

    Returns `(ok, why)`. `why` names the rule that decided, so a rejection can
    be read back -- a tracker that says no without saying which law was broken
    cannot be debugged, and this repo has paid for silent rejections before.

    `scale` is the widget scale, because every distance here is in WIDGET
    pixels and the widget has two sizes.
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
    if motion.may_teleport and dist_px >= TELEPORT_PX * scale:
        # A teleport is a real jump and this is the class that is allowed one.
        return (True, "teleport")
    if motion.may_teleport:
        return (False, "too far to walk, too near to be a teleport")
    return (False, f"exceeds {motion.max_px_s:g} px/s")


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

    # A teleport is legal for the class that has one, and ONLY as a jump: an
    # in-between distance is still refused, which is the whole care here.
    T = CLASSES["walker_teleport"]
    check("teleport agent admits a big jump", admits(T, 300, 0.2)[0], True)
    check("teleport agent still refuses a mid-range step",
          admits(T, 90, 0.2)[0], False)
    check("non-teleport agent refuses that jump", admits(W, 300, 0.2)[0], False)

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
