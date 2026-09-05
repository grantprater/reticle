"""Cast-anchored ability events: join the HUD tray's charge drops to the minimap.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_cast.py --all
    .\\.venv\\Scripts\\python.exe prototypes\\ability_cast.py <session> --offsets

Why this exists
---------------
`docs/ability-recognition.html` §4 for the pivot, and
**`docs/minimap-entity-model.html` for what an emitted entity IS** -- origin,
bearing, extent, existence, anchor and frame, with a driver PER PARAMETER
rather than per object. This module is the first consumer of that model and the
place its claims get tested; where the two disagree, the disagreement is the
result, not a bug to paper over. Every ability feature in this repo answers
*is this pixel an ability?* -- a candidate at a time, independent of everything
else in the frame. Measured on 85 positives across 9 sessions that framing tops
out at 0.36 precision / 0.68 recall, thirteen features prove near-redundant, and
a fitted weighted combiner loses to their unweighted sum. The bank is exhausted.

This inverts the question. `ability_hud.py` reads the tray's charge drops, which
give **the local player's cast times with slot identity, label-free**, and
`reference/abilities.json` turns a slot into an ability name, a deployment type
and a shape family. So instead of scoring an unexplained blob, ask: *Killjoy's
TURRET was cast at 33.5s -- what appeared on the minimap, and where?*

The point is not that this is a nicer framing. It is that a cast time is read
from HUD STRUCTURE and carries no minimap appearance at all, so it is invariant
to the thing that measurably dominates the current detector: `ability_features`
gains more from per-session z-scoring (0.74 vs 0.64 AUC) than from any weighting,
which says most of its discriminative power is spent on how a session looks.

What this module measures FIRST, and why it is not the detector
----------------------------------------------------------------
Before building a detector on a supervisor, measure whether the supervisor
predicts anything. Two questions, both answerable from data already in hand
(161 hand labels over five sessions, and the tray):

    1. Given a cast, is there a labelled instance of THAT ability near it?
    2. What fraction of labelled positives does the tray explain at all?

**CORRECTED 2026-09-05: ults ARE readable from the tray, and "slot X never
drops" was a defect in the READER, not a property of the widget.** the player: *for
ult the tray cast should be the pips going hollow*. Rendered and then measured
on `02cf738b1c8f`, slot X's teal count goes **909 -> 0 between 28.0s and 28.5s**,
and Sova's first Hunter's Fury label is at **28.2s**. The pips and the bar both
desaturate from teal to grey, so the EXISTING teal mask sees it perfectly.

Two bugs hid it, and they compound:

    ability_hud.casts()   loops `for k in range(3)` -- slot 3 is skipped by
                          construction, on the belief that pips are unreadable
    ability_hud.drawn()   refuses the frame, because after the ult EVERY slot
                          is empty and `drawn` reads that as "tray not rendered"

The second is the `hp`-as-a-death-signal defect that reader's own docstring
warns about, arriving from the other side: it conflates "widget absent" with
"every charge genuinely spent", and an all-spent tray is EXACTLY the state that
follows the last cast of a demo clip.

So ults are reachable for the LOCAL player. Audio is still the answer for
everyone else, and the framing is why that generalises rather than merely
extends: **audio range is roughly the observable range, and roughly what is
worth recording**, so a supervisor bounded by what can be heard is bounded by
what matters.

The search window is DERIVED, not assumed
------------------------------------------
The obvious window is "shortly after the cast". That is wrong for a whole class
of abilities and the corpus says so. A held placeable renders a placement
preview -- with its own cone, for a turret -- while the player walks around
holding it, and the charge does not drop until they COMMIT. So the object is on
the minimap BEFORE the cast time, sometimes for many seconds.

`--offsets` measures the signed gap from each labelled instance to the nearest
cast of its own ability. Measured: 5th percentile -2.2s, median +2.9s, 95th
+11.0s.

**Read neither tail as a detector property -- the player, correcting both:**

* **the negative tail is PLACEMENT HOLD TIME, and it is unbounded.** A player
  can hold a placeable for an entire round, so no percentile of it is a real
  limit; the observed -4.1s is a fact about how long the player happened to hold,
  not about the ability. **Only the ~1-2s before the commit carries positional
  information** -- earlier than that the preview is wherever he was walking.
  So the search window opens ~2s before the cast and no further. A LONG hold is
  not noise to widen a window for, it is its own signal: hesitation, or a player
  repositioning a placement, which is a behavioural event rather than a
  detection problem;
* **the positive tail is DEVICE LIFETIME.** Alarmbot's six labels run +1.9s to
  +14.7s because a persistent device keeps being labelled for as long as it
  exists. The upper bound belongs to the ability, not the detector.

WHERE an ability appears is ability-dependent, and the player anchors it
------------------------------------------------------------------------------
the player, 2026-09-05, on the position problem above: some abilities deploy
globally, some have a deployment RADIUS around the player, and some spawn a
fixed distance from him -- *though maybe not fixed in the 2d minimap
projection, not sure*. Then, narrowing it himself: **Omen's smoke and ultimate
are the only truly GLOBAL abilities in the game.**

That second sentence is the load-bearing one. If only two abilities are
unbounded, then **for everything else the shipped self track constrains where
the object can be**, and distance-from-player is a usable prior on which
candidate in a cast window is the right one -- which is exactly the choice this
module currently refuses to make.

Measured, joining labels to `self_icon_dist` and collapsing rows within 10 px in
one session into one object:

    ability            objs   median   spread    reference "Deployment Type"
    viper toxic screen    3    179.9      5.2    Class 6 Projectile
    sova hunter's fury    9     95.1    172.6    Beam
    radius_ring          15    102.1    141.4    --
    skye regrowth         5     46.8     25.2    --
    killjoy alarmbot      2     39.7     49.3    --
    viper's pit           2     21.4      4.7    Placement

The medians span an order of magnitude and the ORDERING matches the
families: self-centred (Viper's Pit, 21 px), placement radius (Alarmbot, 40 px
and a 49 px spread across two placements), extended object (a beam and a radius
ring, spread > 140 px because the object itself is long).

**Do not read this as a fitted prior. n is 1-3 PLACEMENTS per ability.**
Toxic Screen's tight 5.2 px looks like the strongest evidence for the
fixed-distance family and is the weakest row in the table: all three points come
from ONE cast, three positions along one wall, so the spread is WITHIN an object
rather than across placements. The 10 px collapse splits a long object into
pieces, which is right for a device and wrong for a wall. This is a mechanism
with a plausible shape, not a measurement to fit against.

**The reference's `Deployment Type` is NOT this axis, and wiring it in as the
prior would be a mistake.** Viper's Pit and Killjoy's TURRET are both
"Placement" and sit at completely different distances; Toxic Screen is a "Class
6 Projectile". The field describes HOW an ability is deployed, not WHERE
relative to the player. It is also absent on 47 of 121 abilities.

What a cast can and cannot be joined to
----------------------------------------
A label carries a canonical `category_id`, so `killjoy:turret` joins to a TURRET
cast by name. Three label classes carry no agent and cannot:

    radius_ring    the radius circle a deployed device draws -- belongs to a
                   device, but the label does not say which
    place_color    the held/placement state
    smoke          deployed smokes, which look alike whoever threw them

They are reported separately rather than silently dropped or forced into a
guess. `reticle` never guesses a value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import ability_hud as ah                                              # noqa: E402

STORE = Path.home() / "reticle-store"
LAB = STORE / "labels" / "ability"
CACHE = STORE / "casts"
CAND = STORE / "labels" / "ability_candidates"
#: Prototype output. NOT `l2/` -- stage 03 has no schema yet and this
#: must not look like it is claiming one.
EVENTS = STORE / "events" / "ability"

#: The POSITION window, which is not the join window and must not be set
#: from it. The join is asked "does a cast predict an instance of this
#: ability", and wants the ability's whole lifetime -- Alarmbot is still
#: being labelled +14.7s after its cast. Position is asked "which object
#: appeared", and every second of extra window adds candidates that were
#: never the answer: measured, widening from +/-2s to +15s left the number
#: of CORRECT picks unchanged at 3 and turned 5 scoreable events into 11.
#: Before the cast, the player: only the ~1-2s prior to the commit carries
#: positional information -- earlier than that a held placeable's preview
#: is wherever the player happened to be walking.
POS_PRE, POS_POST = 2.0, 2.0

#: A RE-USABLE ability fires over several seconds, so a window sized for a
#: single placement truncates it. Sova's Hunter's Fury put 3 of its 10 labelled
#: fragments inside +/-2s and the other 7 at 30.7-33.2s, entirely outside.
#:
#: Whether the ability is re-usable at all is DERIVED, not listed: 12 of the
#: reference's 121 descriptions say RE-USE, and they are the right 12 --
#: Hunter's Fury, Cypher's Spycam, Jett's Tailwind, Skye's Regrowth, and BOTH
#: of Viper's, which is the resource-bar wrinkle arriving from the game's
#: own text rather than from memory.
#:
#: **The 6.0 is NOT derived and must not be read as if it were. the player flagged
#: it: "which you said is 5 seconds I would verify that."** The description says
#: the ability can be re-used *"while the ability timer is active"* and the
#: infobox does not state that timer's duration, so the reference cannot supply
#: it. 6.0 covers the 4.95 s spread observed in ONE clip (labels 28.20-33.15 s
#: against a cast at 28.5 s) with margin. That is a constant fitted to a single
#: observation, which is the class of thing this repo has been burned by --
#: treat it as provisional and re-measure on a second re-usable cast.
#:
#: Affordable only because the extending signature is self-validating: a wider
#: window adds candidates, and each one either joins a group that extends
#: monotonically outward from a shared origin or it does not.
POS_POST_REUSE = 6.0

#: Fragments of one object: `ability_corpus`'s rule, reused rather than
#: reinvented -- same onset, adjacent centroid.
ONSET_S, DIST_PX = 0.30, 60

#: A driver belongs to a PARAMETER, not to an object -- the central claim of
#: `docs/minimap-entity-model.html`, and it came from a flat per-object table
#: failing here first. Killjoy's turret has a FIXED origin and an
#: ENEMY-REACTIVE bearing; her alarmbot has an enemy-reactive origin and no
#: bearing at all. One label per object cannot say that.
#:
#: **Unlisted abilities are `unknown`, NOT a default.** Defaulting 121 abilities
#: to fixed/absent/none would assert 121 facts nobody has established, and the
#: model's own rule is that absent-by-construction and unknown-by-refusal are
#: different answers. This table holds what the player has actually said.
def _P(origin="fixed", bearing="absent", extent="none"):
    return {"origin": origin, "bearing": bearing, "extent": extent}


PARAMS = {
    ("killjoy", "alarmbot"): _P(origin="enemy-reactive"),
    ("killjoy", "turret"): _P(bearing="enemy-reactive"),
    ("sova", "owl drone"): _P(origin="piloted", bearing="piloted"),
    ("tejo", "stealth drone"): _P(origin="piloted", bearing="piloted"),
    ("fade", "prowler"): _P(origin="piloted", bearing="piloted"),
    ("skye", "trailblazer"): _P(origin="piloted", bearing="piloted"),
    ("skye", "guiding light"): _P(origin="piloted", bearing="piloted"),
    ("cypher", "spycam"): _P(bearing="aimed"),
    ("cypher", "trapwire"): _P(bearing="fixed", extent="extending"),
    ("phoenix", "blaze"): _P(bearing="fixed", extent="freeform"),
    ("viper", "toxic screen"): _P(bearing="fixed", extent="extending"),
    ("sova", "hunter's fury"): _P(bearing="fixed", extent="extending"),
    # Rotation-invariant: bearing ABSENT by construction, radius fixed.
    ("viper", "poison cloud"): _P(extent="radius"),
    ("viper", "viper's pit"): _P(extent="radius"),
    ("jett", "cloudburst"): _P(extent="radius"),
    ("brimstone", "sky smoke"): _P(extent="radius"),
    ("omen", "dark cover"): _P(origin="global", extent="radius"),
}

UNKNOWN = {"origin": "unknown", "bearing": "unknown", "extent": "unknown"}


def params_of(agent, ability):
    return PARAMS.get(((agent or "").lower(), (ability or "").lower()), UNKNOWN)


def reusable(agent, ability):
    """Does the official description say the ability can be RE-USED?"""
    ref = json.loads((STORE / "reference" / "abilities.json").read_text())["agents"]
    a = ref.get(agent)
    if not a or not ability:
        return False
    b = next((x for x in a["abilities"] if x["name"].lower() == ability.lower()),
             None)
    return bool(b) and "RE-USE" in (b.get("description") or "").upper()


BEARING_TOL = 15.0


def bearing_group(rows):
    """Fragments sharing a BEARING from the earliest candidate -> one group.

    For an `extending` extent the fragments are the ANIMATION tracing the
    deployment vector, so they share a bearing from the origin rather than an
    onset. `prototypes/ability_extent.py` has the measurement and its caveat.

    **Clustered by sorting and splitting at gaps, NOT greedily.** The first
    version walked the candidates in time order and joined each to the first
    group whose RUNNING MEAN was within tolerance. That is order-dependent, and
    it showed: widening the window for Sova's re-usable ult changed which bolts
    came back -- +45 and +78 degrees became +78 and +170 -- because one extra
    candidate at an intermediate bearing bridged two clusters and dragged the
    mean. A result that moves when an unrelated candidate enters the window is
    not a measurement. Sorting the bearings and splitting wherever the gap to
    the next exceeds the tolerance depends only on the SET, not its order.
    """
    rows = sorted(rows, key=lambda c: c[0])
    if len(rows) < 2:
        return [list(rows)] if rows else []
    ox, oy = rows[0][1], rows[0][2]
    bs = sorted(((math.degrees(math.atan2(r[2] - oy, r[1] - ox)) % 360.0, r)
                 for r in rows[1:]), key=lambda z: z[0])
    if not bs:
        return [[rows[0]]]
    # circular gaps, including the wrap from the last bearing back to the first
    gaps = [(bs[i + 1][0] - bs[i][0], i) for i in range(len(bs) - 1)]
    gaps.append((360.0 - bs[-1][0] + bs[0][0], len(bs) - 1))
    cuts = sorted(i for g, i in gaps if g > BEARING_TOL)
    if not cuts:
        return [[rows[0]] + [r for _b, r in bs]]
    out, start = [], (cuts[-1] + 1) % len(bs)
    order = [(start + k) % len(bs) for k in range(len(bs))]
    cur = []
    for k, idx in enumerate(order):
        cur.append(bs[idx][1])
        if idx in cuts:
            out.append([rows[0]] + cur)
            cur = []
    if cur:
        out.append([rows[0]] + cur)
    return out or [[rows[0]]]


def extending_entities(gs):
    """Every group that behaves like an EXTENDING entity. May be more than one.

    Not a size heuristic -- the last two of those cost a wrong answer each
    today. This is the entity model's own definition applied as a test: an
    extending extent animates OUTWARD along its bearing, so its fragments must
    show distance from the origin INCREASING with time. A group that merely
    shares a bearing does not qualify.

    Requires three distinct positions, because two points are collinear with
    any origin by construction and agree inside the tolerance ~8% of the time
    by chance.

    **Returns a LIST, because a cast produces 0..N entities and not exactly
    one.** That was an ontology error in the first version of this module, and
    the game's own data says so: Sova's Hunter's Fury is *"three long-range,
    wall-piercing energy blasts ... can be RE-USED up to two more times while
    the ability timer is active"*. Treating a second qualifying group as
    ambiguity threw away a real entity.

    **The count is variable and UP TO three, not three.** the player: *Sova ult does
    not have to have exactly 3 entities. Can be fired 0-3 times within the time
    window.* So finding three in one clip is what that cast did, never a spec to
    validate against -- and an event carrying fewer is not evidence of a miss.
    The same reading applies to every re-usable ability: the reference gives a
    MAXIMUM, and the log records what happened.
    """
    ok = []
    for g in gs:
        seen, uniq = set(), []
        for c in sorted(g, key=lambda c: c[0]):
            if (c[1], c[2]) not in seen:
                seen.add((c[1], c[2]))
                uniq.append(c)
        if len(uniq) < 3:
            continue
        ox, oy = uniq[0][1], uniq[0][2]
        d = [((c[1] - ox) ** 2 + (c[2] - oy) ** 2) ** 0.5 for c in uniq]
        # non-decreasing, with a few px of slack for detection jitter
        if all(b >= a - 4.0 for a, b in zip(d, d[1:])) and d[-1] > d[0]:
            ok.append(uniq)
    return ok


def _bearing(g):
    """Mean bearing of a group's fragments from its origin."""
    ox, oy = g[0][1], g[0][2]
    bs = [math.degrees(math.atan2(c[2] - oy, c[1] - ox)) for c in g[1:]]
    return round(sum(bs) / len(bs), 1) if bs else None


def group_for(rows, extent):
    """Grouping conditioned on the object's KIND, which the cast supplies.

    This is the conflict the entity model resolves. `ability_corpus`'s rule --
    onset within 300 ms, centroid within 60 px -- encodes "appeared at the same
    moment", which is right for a device that pops into existence and wrong for
    anything that extends: Viper's Toxic Screen fragments are 23-41 px apart,
    well inside DIST_PX, but span 2.85 s. The extent driver says which rule
    applies, and the cast is what tells you the extent driver before you group.
    """
    return bearing_group(rows) if extent == "extending" else group(rows)


def group(rows):
    """Fragments of one object -> one group. `ability_corpus`'s rule."""
    out = []
    for r in sorted(rows, key=lambda c: c[0]):
        for g in out:
            if abs(g[0][0] - r[0]) <= ONSET_S and any(
                    (r[1] - m[1]) ** 2 + (r[2] - m[2]) ** 2 <= DIST_PX ** 2
                    for m in g):
                g.append(r)
                break
        else:
            out.append([r])
    return out

#: Slot letter for each reference `slot` field. Confirmed against the reference
#: for five agents: Sova's Grenade is Owl Drone, which is C in game.
SLOT_OF = {"Grenade": "C", "Ability1": "Q", "Ability2": "E", "Ultimate": "X"}

#: Label classes that name no agent -- see the module docstring.
GENERIC = {"radius_ring", "place_color", "smoke", "smoke_deployed", "audio radius"}


def agent_of(sid) -> str | None:
    """The session's agent, from the manifest tags matched to the reference."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    ref = json.loads((STORE / "reference" / "abilities.json").read_text())["agents"]
    low = {a.lower(): a for a in ref}
    for t in man.get("tags", []):
        if t.lower() in low:
            return low[t.lower()]
    return None


def kit(agent) -> dict[str, str]:
    """slot letter -> ability name, for one agent."""
    ref = json.loads((STORE / "reference" / "abilities.json").read_text())["agents"]
    out = {}
    for b in ref[agent]["abilities"]:
        k = SLOT_OF.get(b.get("slot"))
        if k:
            out[k] = b["name"]
    return out


def tray_casts(sid, step_s=0.5, use_cache=True):
    """[(t_s, slot, ability, suspect)] for one session, cached on disk.

    The scan re-decodes the clip, so the result is cached -- but keyed on the
    step, because a different sampling rate is a different measurement and
    silently returning the old one would be the stale-artefact defect that
    `built_by` exists to catch elsewhere.
    """
    # Resolve the agent BEFORE decoding. Without a named agent a slot cannot
    # become an ability, so the scan would be thrown away -- and the scan is the
    # expensive half (a full re-decode of the clip).
    agent = agent_of(sid)
    if agent is None:
        return [], None
    CACHE.mkdir(parents=True, exist_ok=True)
    # Stamp the cache with a hash of the READER, not just the session and step.
    # CLAUDE.md: stamp every cached artefact with the code that built it -- the
    # one convention in that table with zero recurrences. Reading slot 3 changed
    # what `casts()` returns, and a cache keyed on (session, step) alone would
    # have served the old answer forever.
    src = hashlib.blake2b(Path(ah.__file__).read_bytes(), digest_size=4).hexdigest()
    f = CACHE / f"{sid}.step{step_s}.{src}.json"
    if use_cache and f.exists():
        rows = json.loads(f.read_text())
    else:
        ts, counts, clean = ah.scan(sid, step_s=step_s)
        if not len(ts):
            return [], None
        rows = [[t, k, a, b, bool(s)] for t, k, a, b, s in ah.casts(ts, counts, clean)]
        f.write_text(json.dumps(rows))
    k = kit(agent)
    return [(t, slot, k.get(slot), sus) for t, slot, _a, _b, sus in rows], agent


def labelled(sid):
    """[(t_s, x, y, category_id, ability_lc, kind)] for the positives."""
    f = LAB / f"{sid}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("not_ability"):
            continue
        cid = r.get("category_id")
        ab = (r.get("ability") or "").lower()
        kind = ("uncertain" if r.get("uncertain")
                else "generic" if (cid in GENERIC or not r.get("agent"))
                else "named")
        out.append((r["t_ms"] / 1000.0, r["x"], r["y"], cid, ab, kind))
    return out


def offsets(sid, step_s=0.5):
    """Signed gap from each NAMED label to the nearest cast of its own ability.

    Negative means the label is BEFORE the cast -- the placement-preview case.
    """
    cs, agent = tray_casts(sid, step_s)
    if agent is None:
        return [], None
    out = []
    for t, x, y, cid, ab, kind in labelled(sid):
        if kind != "named":
            continue
        same = [c for c in cs if c[2] and c[2].lower() == ab]
        if not same:
            out.append((t, ab, None, None))
            continue
        best = min(same, key=lambda c: abs(t - c[0]))
        out.append((t, ab, t - best[0], best[1]))
    return out, agent


def join(sid, pre, post, step_s=0.5):
    """Match casts to labelled instances of the same ability inside a window.

    Returns (rows, agent) where each row is one CAST:
        (t, slot, ability, suspect, [labels matched])
    """
    cs, agent = tray_casts(sid, step_s)
    if agent is None:
        return [], None
    labs = labelled(sid)
    rows = []
    for t, slot, ab, sus in cs:
        if ab is None:
            rows.append((t, slot, None, sus, []))
            continue
        hit = [L for L in labs
               if L[5] == "named" and L[4] == ab.lower()
               and -pre <= (L[0] - t) <= post]
        rows.append((t, slot, ab, sus, hit))
    return rows, agent


def candidates(sid):
    """[(t_s, x, y, n_obs, duration_s)] from the scan, or [] if none."""
    f = CAND / f"{sid}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        out.append((r["t_ms"] / 1000.0, r["x"], r["y"],
                    r.get("n_observations") or 0,
                    (r.get("duration_ms") or 0) / 1000.0))
    return out


def emit(sid, pre=POS_PRE, post=POS_POST, step_s=0.5):
    """One event per CAST, with a position attached only when one is available.

    The event is the deliverable and the position is enrichment. A cast time
    carries an agent, a slot and an ability with no minimap evidence at all, and
    that is already a usable event -- the player, on this exact channel: *ship partial
    identification. Detect > localise > classify, and emit what is known at each
    level rather than waiting.* An ability that draws nothing on the widget
    (a flash before a peek, say) still produces a real event here, and those are
    precisely the ones no minimap detector can ever reach.

    So `x`/`y` are **null** unless the window contains EXACTLY ONE candidate,
    and they are never guessed.

    **That rule replaces a nearest-onset heuristic, which was measured and does
    not work.** Taking the candidate whose onset is closest to the cast picked
    the labelled object 3 times out of 5 at the tightest window and 3 out of 11
    at the widest -- the count of correct picks never rose, so widening the
    window added only errors, and the median miss went 0 px -> 36 px. The three
    it got right are the three where there was nothing to choose between.

    The honest consequence, and it tempers the design doc's SS4: **a cast time
    buys the EVENT cheaply and does not buy the POSITION cheaply.** Even at
    +/-1.5s around a known cast, half the events still have more than one
    candidate in reach, and choosing between them is the same weak per-pixel
    problem as before. Time and identity come free from HUD structure; location
    still needs a detector.

    A multi-candidate window therefore emits `x`/`y` null and carries the
    candidates themselves in `candidates`, so nothing is discarded and a later
    scorer can choose without re-deriving the window.

    **`x`/`y` assume the object is a POINT, and for a region it is not.** the player,
    confirming Toxic Screen: *it's a long straight line.* So its three labels are
    three points along ONE object, and the "right" position for that event is an
    extent, not a coordinate -- a wall has a start and an end, a smoke has a
    radius. This is the icon-vs-region split in `prototypes/CLAUDE.md` arriving
    in the event schema, and it means a multi-candidate window has two entirely
    different causes that this module currently cannot tell apart:

        several candidates, several objects   -> genuinely ambiguous, refuse
        several candidates, ONE region        -> not ambiguous at all; they are
                                                 fragments and want grouping

    Refusing is right for the first and wrong for the second, and today it does
    both. Grouping fragments of one region before selecting is the fix, and
    `ability_corpus` already has the grouping this needs -- it is just not lifted
    out where this module can call it. Until then, read `position_ambiguous` as
    "more than one candidate", never as "more than one object".

    ORIGIN PLUS AN OPTIONAL DEPLOYMENT VECTOR, and one named exception
    ------------------------------------------------------------------------
    the player, 2026-09-05, and it dissolves the point-vs-region problem rather than
    working around it: **every ability except Phoenix's wall can be described by
    an ORIGIN POINT and a DEPLOYMENT VECTOR (orientation).** Phoenix's Blaze is
    steered while it extends, so it is genuinely freeform -- *though often it's
    either just straight or curved in one direction*.

    One representation for both families this repo has been treating as
    separate. A turret is an origin and a facing; a wall is an origin and a
    direction; a beam is an origin and a bearing. It is also the primitive
    `minimap_cone.icon_facing()` already returns -- `(cx, cy, angle)` -- so the
    player's cone, a deployable's cone and a placed wall are all the same shape
    of measurement.

    **The vector is OPTIONAL, and its absence is a fact about the ability rather
    than a failed fit.** the player: *standard smokes are rotation-invariant.* So a
    smoke has an origin and no orientation at all -- not a degenerate one, none
    -- and that is knowable from the ability before any pixel is read. The
    distinction is load-bearing because the two nulls mean opposite things:

        orientation null BY CONSTRUCTION   the ability has no orientation.
                                           Information, and complete.
        orientation null BY REFUSAL        the fit could not answer. A gap.

    Fitting an orientation to a rotation-invariant object would be a confident
    answer to a question with no answer, which this repo has already paid for
    once and guards against: `minimap_ring_fit.LOBE_MIN_FRAC` exists precisely so
    a perfect circle -- a Cypher cam -- cannot report a bearing out of noise.
    Same principle, one level up.

    Two things follow that are worth more than the schema tidy-up:

    * **the turret's cone direction IS its deployment vector.** Observing one
      gives the other, which closes a loop with the deployable-cone work: a cone
      anchored somewhere other than the player both needs an orientation and
      supplies one;
    * **it re-justifies the deferred shape features, for a different job.**
      `cv2.minAreaRect` was deferred as a discriminative feature and that
      deferral still stands -- adding to a near-redundant bank does not help. But
      the long axis of a grouped region's minAreaRect **is** the deployment
      vector, and measuring the orientation of an object whose identity is
      already known from the cast is not classification at all. Detection-first
      then measure, rather than measure-in-order-to-classify.

    CORRECTED SAME DAY: a POSE IS NOT ENOUGH, and the driver is the point
    ------------------------------------------------------------------------
    the player, withdrawing his own claim within the hour: *deployment position and
    orientation are not sufficient to fully describe ability icons/animations on
    the minimap.* Objects change state AFTER deployment, and what matters is not
    that they move but **what drives the motion**:

        driver              what moves                     examples
        static              nothing                        most placed devices
        ENEMY-REACTIVE      the icon translates or turns    Killjoy's Alarmbot
                            in response to an enemy         moves toward enemies;
                                                            her TURRET snaps onto
                                                            one in its cone
        PLAYER-PILOTED      translate and rotate under      Sova's drone, Tejo's
                            direct control                  drone, Fade's Prowler,
                                                            Skye's dog AND birds
        PLAYER-AIMED        rotate only, while the player   Cypher's cam
                            is viewing through it
        freeform-at-cast    shape is steered as it forms    Phoenix's wall

    So an event is a TRAJECTORY with a lifetime, not a pose. The driver is a
    per-ability property, knowable from the kit rather than from pixels.

    **The enemy-reactive row is worth more than the schema.** `CLAUDE.md` records
    opponent priors as *blocked, for now: needs enemy positions, which no capture
    of one's own screen contains.* But an Alarmbot that moves is moving TOWARD an
    enemy, and a turret that snaps is snapping ONTO one -- so the motion of your
    own utility is an enemy detection, derived from your own screen, at a known
    position and time. That is a new source for something recorded as
    structurally unavailable, and it costs no new extractor: it is the position
    track applied to an object the cast already identified.

    **the player hedged both** (*I believe its icon moves*, *I believe it might rotate
    its icon*), and **the demo corpus structurally cannot settle them**: a solo
    custom game has no enemies, so an enemy-reactive object has nothing to react
    to. That is the CASTABLE BUT UNREPRESENTATIVE category `prototypes/CLAUDE.md`
    already defines for Skye's seekers, arriving for a second ability. Absence of
    motion in these clips is not evidence.

    What the corpus DOES show, from the labels: **Sova's Owl Drone translates 18
    px in 0.9s** ((243,143) -> (244,161)), which is the piloted row confirmed.
    The Alarmbot drifts ~10 px over 16s, consistent with static, as it should be
    with no enemy present.

    **The exceptions are NAMED and few**, which is what makes any of this usable.
    This project keeps landing on that shape: Omen's smoke is the only ability
    that translates while DEPLOYING, Omen's smoke and ultimate are the only
    globally-deployed ones, Phoenix's wall is the only freeform region. A rule
    plus a short enumerated exception list is a complete model; "some abilities
    might" is not. The list is longer than it looked this morning, and it is
    still a list.

    RESULT of the two-field test, 2026-09-05
    ------------------------------------------------------------------------
    Adding `anchor` and `driver` moved positions from 10 to 12 of 24, and the
    selection check from 2/2 to 2/3 -- so one of the two new answers was WRONG.
    Read that as three separate findings, because they point different ways:

    * **the anchor edge is real but narrow.** Jett's second Cloudburst had two
      candidates that are one object, and merging them is correct and costs
      nothing. That refusal was never ambiguity;
    * **the driver edge, as implemented, was a heuristic wearing a type.**
      Taking the earliest group as a piloted object's origin is nearest-onset
      again, and it put Trailblazer 79 px from its label. Removed;
    * **most refusals are GENUINE multi-object windows, not bookkeeping.**
      Grouping barely dents them -- ALARMBOT 14 candidates to 10 objects,
      TURRET 10 to 7, Hunter's Fury 6 to 4. So the position problem is not
      waiting on a better ontology; it is waiting on the detector or the
      distance prior.

    **And one specific defect the test exposed, which IS worth fixing.** Viper's
    Toxic Screen has 5 candidates in its window and groups into 5 objects, when
    the player says it is one long straight line. The fragments are spatially
    adjacent -- (243,367), (283,375), (306,376), gaps of 23-41 px, well inside
    `DIST_PX` -- but they span **2.85 seconds** against an `ONSET_S` of 0.30.
    `ability_corpus`'s rule encodes "appeared at the same moment", which is
    right for a device that pops into existence and wrong for a region that
    GROWS: a wall extends, a smoke expands, a beam sweeps.

    That is the abstraction earning its place in the one way it actually did:
    **the grouping rule should be conditioned on the object's kind, and the cast
    is what tells you the kind before you group.** A compact device wants a
    300 ms window; an extending region wants seconds. Not implemented -- it
    would be fitted to one wall -- but the cause is measured and the fix is
    named.

    NOT changed here: the event still carries a bare `x`/`y`. Adding an
    `orientation` field would want three states (a value, null-by-construction,
    null-by-refusal), the region grouping, and an actual fit behind it -- so it
    is a real piece of work rather than a field.
    """
    cs, agent = tray_casts(sid, step_s)
    if agent is None:
        return [], None
    cands = candidates(sid)
    src = hashlib.blake2b(Path(__file__).read_bytes(), digest_size=4).hexdigest()
    out = []
    for t, slot, ab, sus in cs:
        post_t = POS_POST_REUSE if reusable(agent, ab) else post
        win = [c for c in cands if -pre <= (c[0] - t) <= post_t]
        par = params_of(agent, ab)
        gs = group_for(win, par["extent"])
        # THE TEST (2026-09-05): does typing the edges turn a refusal into an
        # answer? Measured on all 24 events -- see RESULT in the docstring.
        # ANCHOR earns a narrow place; DRIVER did not, as first implemented.
        anchor = None
        exts = extending_entities(gs) if par["extent"] == "extending" else []
        ext = exts[0] if len(exts) == 1 else None
        if ext is not None:
            # The extending entity IS the group that extends. Its position is
            # its ORIGIN -- where the wall or the bolt started -- not a centroid
            # over an object that has length.
            pick = (ext[0][0], ext[0][1], ext[0][2], 0, 0)
            anchor = f"extending origin ({len(ext)} fragments)"
        elif len(exts) > 1:
            # Several extending objects from one cast. NOT ambiguity -- an event
            # with no single position, which is the honest answer for an ult
            # that fires three bolts. They ride in `entities`.
            pick = None
            anchor = f"{len(exts)} extending entities"
        elif len(win) == 1:
            pick, anchor = win[0], "single candidate"
        elif len(gs) == 1:
            g = gs[0]
            pick = (min(c[0] for c in g),
                    int(sum(c[1] for c in g) / len(g)),
                    int(sum(c[2] for c in g) / len(g)), 0, 0)
            anchor = f"fragments merged ({len(g)})"
        else:
            # A `piloted` branch taking the EARLIEST group as the track origin
            # was tried and removed: it is the nearest-onset heuristic in
            # disguise, and it put Skye's Trailblazer at (80,153) against a
            # label at (159,138) -- 79 px wrong. A driver is real domain
            # knowledge; that was not a valid way to spend it. A piloted track
            # needs actual chaining under a speed bound, not "take the first".
            pick = None

        # BEARING, three-valued exactly as the entity model requires. It is
        # measured only where the ability HAS one and the fit has something to
        # fit: an extending extent whose group holds the origin plus two or
        # more fragments. A single pair agrees inside the tolerance about 8% of
        # the time by chance, which is not a measurement.
        # BEARING is a parameter in its own right and is NOT gated on having
        # resolved the position. Coupling them was a bug in the first version of
        # this module, not something the entity model asks for: the two are
        # separate fields with separate drivers, and an extending entity's
        # bearing is measurable exactly when its fragments are, whether or not
        # anything else in the window is ambiguous.
        bearing, bearing_state = None, "unknown"
        if par["bearing"] == "absent":
            bearing_state = "absent"                 # rotation-invariant
        elif ext is not None:
            bearing = _bearing(ext)
            bearing_state = f"fitted from {len(ext)} fragments"
        elif len(exts) > 1:
            bearing_state = f"one per entity ({len(exts)})"

        entities = [{"origin_x": int(e[0][1]), "origin_y": int(e[0][2]),
                     "bearing": _bearing(e), "n_fragments": len(e),
                     "extent": "extending"} for e in exts]
        out.append({
            "session_id": sid,
            "t_ms": int(round(t * 1000)),
            "source": "tray",
            "slot": slot,
            "agent": agent,
            "ability": ab,
            "confidence": "suspect" if sus else "clean",
            "x": None if pick is None else int(pick[1]),
            "y": None if pick is None else int(pick[2]),
            "position_from": anchor,
            "drivers": par,
            "bearing": bearing,
            "bearing_state": bearing_state,
            "entities": entities,
            "n_entities": len(entities),
            "frame": "map",
            "position_dt_s": None if pick is None else round(pick[0] - t, 2),
            "position_ambiguous": pick is None and len(win) > 0,
            "n_candidates": len(win),
            "n_objects": len(gs),
            "candidates": [{"t_ms": int(round(c[0] * 1000)), "x": c[1],
                            "y": c[2]} for c in win],
            "window_s": [-pre, post_t],
            "reusable": reusable(agent, ab),
            "built_by": src,
        })
    return out, agent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?")
    ap.add_argument("--all", action="store_true", help="every session with labels")
    ap.add_argument("--offsets", action="store_true",
                    help="signed label-to-cast gaps, to DERIVE the window")
    ap.add_argument("--pre", type=float, default=12.0,
                    help="seconds BEFORE a cast to search (placement preview)")
    ap.add_argument("--post", type=float, default=8.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--emit", action="store_true",
                    help="write one event per cast to <store>/events/ability/")
    ap.add_argument("--pos-pre", type=float, default=POS_PRE,
                    help="seconds before a cast to look for its object. NOT the"
                         " join window -- see POS_PRE")
    ap.add_argument("--pos-post", type=float, default=POS_POST)
    a = ap.parse_args()

    sids = ([p.stem for p in sorted(LAB.glob("*.jsonl")) if ".bak" not in p.name]
            if a.all else [a.session])
    if not sids or sids == [None]:
        ap.error("give a session or --all")

    if a.offsets:
        print("Signed gap from each labelled instance to the nearest cast of its")
        print("own ability. NEGATIVE = the object is on the minimap BEFORE the")
        print("charge drops, i.e. it was being held and placed.\n")
        print(f"{'session':<14}{'ability':<18}{'n':>4}{'median dt':>11}"
              f"{'min':>8}{'max':>8}   sign")
        allsigned = []
        for sid in sids:
            try:
                rows, agent = offsets(sid, a.step)
            except Exception as e:                                  # noqa: BLE001
                print(f"{sid:<14}SKIPPED ({e})")
                continue
            if agent is None:
                continue
            by = {}
            for t, ab, dt, slot in rows:
                by.setdefault(ab, []).append(dt)
            for ab, ds in sorted(by.items()):
                got = [d for d in ds if d is not None]
                if not got:
                    print(f"{sid[:12]:<14}{ab[:17]:<18}{len(ds):>4}"
                          f"{'no cast':>11}{'':>8}{'':>8}   -- ult or unspent")
                    continue
                allsigned += got
                neg = sum(1 for d in got if d < 0)
                sign = ("all before" if neg == len(got) else
                        "all after" if neg == 0 else f"{neg}/{len(got)} before")
                print(f"{sid[:12]:<14}{ab[:17]:<18}{len(got):>4}"
                      f"{np.median(got):>11.1f}{min(got):>8.1f}{max(got):>8.1f}"
                      f"   {sign}")
        if allsigned:
            q = np.percentile(allsigned, [5, 50, 95])
            print(f"\npooled n={len(allsigned)}  5th {q[0]:.1f}s  median {q[1]:.1f}s"
                  f"  95th {q[2]:.1f}s")
            print("Read the SIGN column first. A class that is consistently"
                  " 'all before'\nis a held placeable and the window must open"
                  " before the cast, not after.")
        return 0

    if a.emit:
        EVENTS.mkdir(parents=True, exist_ok=True)
        tot = dict(ev=0, pos=0, ent=0, amb=0, nocand=0)
        dists, chosen_right = [], 0
        print(f"Emitting to {EVENTS}  (position window -{a.pos_pre:.1f}s .. +{a.pos_post:.1f}s)")
        print("")
        print(f"{'session':<14}{'agent':<10}{'events':>7}{'with pos':>9}"
              f"{'multi':>7}{'ambig':>7}{'no cand':>8}")
        for sid in sids:
            try:
                evs, agent = emit(sid, a.pos_pre, a.pos_post, a.step)
            except Exception as e:                                  # noqa: BLE001
                print(f"{sid:<14}SKIPPED ({e})")
                continue
            if agent is None:
                continue
            f = EVENTS / f"{sid}.jsonl"
            f.write_text("".join(json.dumps(e) + chr(10) for e in evs),
                         encoding="utf-8")
            npos = sum(1 for e in evs if e["x"] is not None)
            nent = sum(1 for e in evs if e["x"] is None and e["n_entities"] > 1)
            namb = sum(1 for e in evs if e["x"] is None and e["n_entities"] <= 1
                       and e["n_candidates"] > 0)
            nnone = sum(1 for e in evs if e["n_candidates"] == 0)
            tot["ev"] += len(evs)
            tot["pos"] += npos
            tot["ent"] += nent
            tot["amb"] += namb
            tot["nocand"] += nnone
            print(f"{sid[:12]:<14}{agent:<10}{len(evs):>7}{npos:>9}{nent:>7}"
                  f"{namb:>7}{nnone:>8}")

            # Did the selection rule pick the RIGHT candidate? Only answerable
            # where a label of that ability exists in the same window.
            labs = labelled(sid)
            for e in evs:
                if e["x"] is None or not e["ability"]:
                    continue
                t = e["t_ms"] / 1000.0
                same = [L for L in labs if L[5] == "named"
                        and L[4] == e["ability"].lower()
                        and -a.pos_pre <= (L[0] - t) <= a.pos_post]
                if not same:
                    continue
                d = min(((e["x"] - L[1]) ** 2 + (e["y"] - L[2]) ** 2) ** 0.5
                        for L in same)
                dists.append(d)
                chosen_right += (d < 1.0)
        print(f"{'TOTAL':<14}{'':<10}{tot['ev']:>7}{tot['pos']:>9}"
              f"{tot['ent']:>7}{tot['amb']:>7}{tot['nocand']:>8}")
        print("")
        print(f"{tot['ev']} events written, and they partition cleanly:")
        print(f"  {tot['pos']:>3} carry ONE position -- a single candidate,"
              " fragments of one object,")
        print("      or an extending object resolved to its origin")
        print(f"  {tot['ent']:>3} carry SEVERAL entities -- one cast, N objects."
              " Sova's ult is three bolts")
        print("      from one origin, so an event with no single x/y is the"
              " honest answer, not a refusal")
        print(f"  {tot['amb']:>3} REFUSED a position -- more than one candidate"
              " and nothing to choose on;")
        print("      the candidates ride along for a later scorer")
        print(f"  {tot['nocand']:>3} had NO candidate at all, and many of those"
              " are CORRECT: a grenade,")
        print("      flash, molotov or dash draws nothing on the widget and is"
              " still a real cast.")
        print("      That is the half no minimap detector can ever reach.")
        if dists:
            import statistics
            print("")
            print("Selection check, where a label of that ability exists in the"
                  f" window (n={len(dists)}):")
            print(f"  landed on the labelled object exactly: {chosen_right}"
                  f" / {len(dists)}    median miss"
                  f" {statistics.median(dists):.1f} px")
            print("  Only events whose window held exactly ONE candidate are"
                  " scored here -- the rest")
            print("  emit a null position on purpose. On these sessions the"
                  " candidate file and the label")
            print("  file are largely the same positions, so this answers"
                  " 'was the lone candidate the")
            print("  right object', never 'is there an object there'.")
        return 0

    print(f"Cast-anchored join. Window: cast -{a.pre:.0f}s .. +{a.post:.0f}s\n")
    print(f"{'session':<14}{'agent':<9}{'casts':>6}{'named':>7}{'matched':>9}"
          f"{'ults':>6}{'generic':>8}{'unc':>5}")
    T = dict(casts=0, named=0, matched=0, ults=0, ults_matched=0,
             generic=0, unc=0, nolab=0)
    detail = []
    for sid in sids:
        try:
            rows, agent = join(sid, a.pre, a.post, a.step)
        except Exception as e:                                      # noqa: BLE001
            print(f"{sid:<14}SKIPPED ({e})")
            continue
        if agent is None:
            continue
        labs = labelled(sid)
        named = [L for L in labs if L[5] == "named"]
        gen = [L for L in labs if L[5] == "generic"]
        unc = [L for L in labs if L[5] == "uncertain"]
        ultname = (kit(agent).get("X") or "").lower()
        ults = [L for L in named if L[4] == ultname]
        # Key by VALUE, not id(): `join` builds its own label list, so the
        # objects here are different instances of the same rows and an identity
        # test silently counts zero.
        matched = {(L[0], L[1], L[2], L[3]) for r in rows for L in r[4]}
        T["ults_matched"] += sum(1 for L in ults
                                 if (L[0], L[1], L[2], L[3]) in matched)
        T["casts"] += len(rows); T["named"] += len(named)
        T["matched"] += len(matched); T["ults"] += len(ults)
        T["generic"] += len(gen); T["unc"] += len(unc)
        print(f"{sid[:12]:<14}{agent:<9}{len(rows):>6}{len(named):>7}"
              f"{len(matched):>9}{len(ults):>6}{len(gen):>8}{len(unc):>5}")
        detail.append((sid, agent, rows))

    print(f"{'TOTAL':<14}{'':<9}{T['casts']:>6}{T['named']:>7}{T['matched']:>9}"
          f"{T['ults']:>6}{T['generic']:>8}{T['unc']:>5}")

    n, m, u, um = T["named"], T["matched"], T["ults"], T["ults_matched"]
    pct = f" ({m / n:.0%})." if n else "."
    print("")
    print(f"Of {n} agent-named positives the join explains {m}" + pct)
    print(f"{u} of them are ULTIMATES and {um} of those are MATCHED. Slot X is"
          " readable -- the pips desaturate along with the bar -- corrected"
          " 2026-09-05; it was skipped by construction before.")
    print("Where an ult is unmatched the cause is the RECORDING, not the widget:"
          " infinite abilities refills the bar between samples, and a SUSTAINED"
          " ult (Viper's Pit) holds it up while it is active. A missing drop is"
          " no evidence, never \"no cast\".")
    print("")
    print(f"A further {T['generic']} positives carry no agent"
          " (radius_ring / place_color / smoke)"
          f" and {T['unc']} are uncertain; neither joins by name.")

    print("\n=== every cast, and what it explains ===")
    for sid, agent, rows in detail:
        print(f"\n  {sid}  {agent}")
        for t, slot, ab, sus, hit in rows:
            mark = "  SUSPECT" if sus else ""
            if not hit:
                print(f"    {t:7.2f}s  {slot}  {str(ab):<14} --{mark}")
                continue
            dts = ", ".join(f"{L[0] - t:+.1f}s" for L in sorted(hit))
            print(f"    {t:7.2f}s  {slot}  {str(ab):<14} {len(hit)} label"
                  f"{'s' if len(hit) > 1 else ''} at {dts}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
