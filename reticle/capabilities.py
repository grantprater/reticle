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

    hud, regime `transition`      The killfeed reader fires on camera wipes at
                                  EVERY fidelity -- 13 reviewed-empty instants
                                  claimed at native rate, 8 at 15 Hz, up to six
                                  phantom entries in one frame. Reference
                                  fidelity does not meet the frozen tolerance,
                                  so no cheaper tier can be promoted by matching
                                  it. A request that needs killfeed evidence
                                  across a respawn wipe is refused as
                                  `unsupported_regime` rather than answered.

    minimap.self_position         No tier agrees with the native reference on
                                  97% of shared frames; agreement is 0.88-0.91
                                  and NON-MONOTONIC in the rate. `pick_self`
                                  admits `RUN_PX * scale * (step_ms/1000) * 2`,
                                  which is 1.50 px at 60 Hz, and 13.8% of
                                  consecutive steps exceed it there against 0.0%
                                  at 2 Hz. The nearest-to-previous discipline is
                                  abandoned most often at the highest rate, so
                                  reference fidelity is not the quality ceiling
                                  and the comparison has no valid baseline yet.

Add a reader here by running `reticle fidelity-check` and pinning the run that
promoted it, not by declaring what the reader looks like it should manage.
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
                "An unobserved killfeed is not an empty one. 2 Hz missed a "
                "reviewed entry instant (recall 0.9545), so absence below 5 Hz "
                "carries no weight."
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
            "The frozen run scored presence, not how many rows were up. Up to "
            "six phantom entries appear in a single wiped frame."
        ),
        "hud@transition": (
            "The killfeed reader fires on respawn and camera wipes at every "
            "fidelity, reference fidelity included. Fix the detector before "
            "declaring a tier."
        ),
        "minimap.self_position": (
            "No tier reaches the frozen 0.97 agreement, and agreement does not "
            "fall with the rate. pick_self's gate is 1.50 px at 60 Hz and 13.8% "
            "of steps exceed it, so the native reference is the least "
            "track-disciplined read rather than the best one."
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
