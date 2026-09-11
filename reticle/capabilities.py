"""What the shipped readers are VALIDATED to do, and what they are refused.

`acquisition` can plan against any capability a caller invents. That is right for
a contract and wrong for a pipeline: a planner that accepts whatever tier a spec
claims will happily route a request through a rate nobody measured. This module
is the registry of declarations backed by a frozen comparison, and its rule is
that a tier appears here only after `fidelity` scored it against source-reviewed
windows and it met the tolerances frozen with them.

**Most of what the readers can be asked to do is absent from this file, and that
is the content.** The first frozen run (2026-09-09, `c40d950031bb`, six windows,
79.4 s reviewed) promoted exactly one property:

    hud.killfeed_entry_presence   5, 10, 15 Hz and native, regime `standard`
                                  presence recall 1.0000 against reviewed truth

and refused two things outright:

    hud, regime `transition`      The killfeed check now PASSES at every tier:
                                  adjudicated presence takes the confuser false
                                  positives to zero at native, 15, 10, 5 and
                                  2 Hz, and every tier counts the same eleven
                                  entries. It is withheld on coverage, not on
                                  the defect -- one session, one map, two
                                  reviewed wipes. A second reviewed session
                                  promotes it; until then a request needing
                                  killfeed evidence across a respawn wipe is
                                  refused as `unsupported_regime`.

    minimap.self_position         No tier agrees with the native reference on
                                  97% of shared frames. `pick_self`'s gate is
                                  no longer the reason: floored at the fit
                                  error and given the real elapsed time, 15 Hz
                                  goes 0.9030 -> 0.9363 and 10 Hz 0.9068 ->
                                  0.9438. What is left is the SELF RING
                                  FRAGMENTING. On all 69 disagreeing frames at
                                  15 Hz and all 47 at 5 Hz the reference's own
                                  answer sits in the candidate list the cheaper
                                  tier held: two to seven self-coloured blobs a
                                  median 10.3 px apart, which is the ring's own
                                  diameter. The two readers latch onto opposite
                                  arcs of one ring and each stays consistent
                                  with itself -- taking the NEAREST to the
                                  previous point instead of the largest
                                  recovers 15 of 47 at 5 Hz and none at all at
                                  15 Hz. Merge the fragments before promoting a
                                  tier.

Add a reader here by running `reticle fidelity-check` and pinning the run that
promoted it, not by declaring what the reader looks like it should manage.

Owns [owns:reader-capability].
"""
from __future__ import annotations

from .acquisition import ReaderCapability, SamplingTier


CAPABILITIES_VERSION = "capabilities-0.1.0"

# The run that promoted everything below. A tier with no evidence pointer is a
# tier nobody measured.
FROZEN_EVIDENCE = "p3-reference-fidelity-1 @ c40d950031bb, frozen 2026-09-09"

# Named for the rates `fidelity-check` actually scored, so a declaration and its
# evidence cannot drift apart under a rename.
_VALIDATED_HUD_TIERS = (
    SamplingTier("sparse", 5.0),
    SamplingTier("standard", 10.0),
    SamplingTier("motion", 15.0),
    SamplingTier("native", None),
)


def builtin_capabilities() -> dict[str, ReaderCapability]:
    """The registry, keyed by reader name, as `plan_requests` wants it.

    A function rather than a module constant because `ReaderCapability` is
    frozen but the dict is not, and a caller mutating a shared registry would
    change what every later plan is allowed to do.
    """
    return {
        "hud": ReaderCapability(
            reader="hud",
            # Presence only. The reader also reports an entry COUNT and a
            # per-entry mask, and neither was scored by the frozen run, so
            # neither is declared here.
            properties=("killfeed_entry_presence",),
            tiers=_VALIDATED_HUD_TIERS,
            # `transition` is deliberately missing. See the module docstring.
            regimes=("standard",),
            negative_evidence=(
                "An unobserved killfeed is not an empty one. 2 Hz misses two "
                "reviewed entry instants (recall 0.9091) against 1.0000 at "
                "5 Hz and above, so absence below 5 Hz carries no weight."
            ),
        ),
    }


def unvalidated() -> dict[str, str]:
    """Readers and properties this registry deliberately withholds, and why.

    Kept beside the declarations rather than in a document, because the reason a
    capability is absent is the part a caller needs when a plan refuses them.
    """
    return {
        "hud.killfeed_entry_count": (
            "The frozen run scores presence, not how many rows were up. The "
            "adjudicated count agrees at eleven across every tier, which is "
            "consistency and not accuracy -- nobody counted the rows in those "
            "windows. `kf_entries`, the per-frame column, still reaches six on "
            "one wiped frame and is not a count of anything."
        ),
        "hud@transition": (
            "Adjudicated killfeed presence meets the frozen tolerance at every "
            "tier, on ONE session with two reviewed wipes. Withheld for want "
            "of a second reviewed session, not for a known defect."
        ),
        "minimap.self_position": (
            "No tier reaches the frozen 0.97 agreement. The self ring "
            "fragments into two to seven blobs a median 10.3 px apart, and "
            "readers at different rates latch onto different arcs of it -- the "
            "reference's answer is in the candidate list on every disagreeing "
            "frame. Merge the fragments before declaring a tier."
        ),
        "minimap.ally_positions": "Never scored against reviewed truth.",
        "ping.ping_event": "Never scored against reviewed truth.",
        "roster.agent_identity": "Never scored against reviewed truth.",
        "scoreboard.row_observation": "Never scored against reviewed truth.",
        "lineup.portrait_identity": "Never scored against reviewed truth.",
        "*.reduced_spatial": (
            "Every executable tier retains native source/ROI pixels. No reduced "
            "spatial tier has passed a held-out accuracy check."
        ),
    }
