r"""A CAST licenses a JUMP: the tray and the position track as each other's control.

    .\.venv\Scripts\python.exe prototypes\cast_motion.py <session> [--hz 15] [--window 3]
    .\.venv\Scripts\python.exe prototypes\cast_motion.py --teleport-corpus

Recorded 2026-09-06, noting the player had raised it before: *a teleport activated on the
hotbar (or in audio once that's built) should be triggering an expected agent
teleport.*

Why this is the right fix rather than a parallel one
------------------------------------------------------
`minimap.filter_track` now takes a motion class (2026-09-06), and
`jump_census.py --motion` measured what applying one to a whole session does:

    observations kept    default   walker   walker_dash   walker_teleport
    pooled 102,765        88.7%    81.9%       95.0%          89.5%

`walker_teleport` is **+835 net and NEGATIVE on three of five sessions**,
because `admits` gives up the fixed gate's 1.6x slack everywhere in order to
buy jumps in a few places. A session-wide class is the wrong granularity.

A cast is evidence for the class **on a window**, which spends the
permissiveness only where something happened. It also inverts the dependency:
knowing the agent says a jump MAY be legal, knowing a cast happened says a jump
IS EXPECTED. So the two channels become each other's control:

    cast at t AND jump at t     corroboration -- a real teleport, keep it
    jump at t, no cast          a phantom, and filter_track was right
    cast at t, no jump          not a teleport, or the track lost the player --
                                itself a finding

The class map is DERIVED, and it disagrees with the hand-written one
----------------------------------------------------------------------
`reticle/track.py`'s table carries a prose note -- *"Omen x2, Chamber, Veto,
Waylay E, Yoru E"* for `walker_teleport` and *"Jett, Neon, Waylay Q"* for
`walker_dash`. `ability_reference`'s stored table carries a `functions` field
per ability, harvested from the wiki, and reading the classes off that instead
of off a note gives 29 agents for free and disagrees in two places:

* **Waylay E (Refract) is `Invulnerability Mobility`, not Teleport.** *"REACTIVATE
  to speed back to your beacon as a mote of pure light"* -- a fast TRAVEL with a
  duration, not a discontinuity. At 15 Hz it may still cross a whole widget in
  one sample, which makes it a `walker_dash` at worst and not the class the
  note assigns;
* **Raze Q (Blast Pack) is `Dash Displacement`** and is missing from the dash
  note entirely. A satchel jump is one of the largest displacements in the
  game.

Neither is corrected in `track.py` here: this file measures, and a table that
disagrees with a note is a finding to carry, not a licence to edit the note
from a wiki field nobody has checked against footage.

**A wiki field is not a motion model, and the first version of this map proved
it.** Reading `Displacement` as self-movement licensed a jump for Astra,
Breach, Deadlock and Miks -- four ultimates that displace ENEMIES and leave the
caster still. Four gates opened for phantoms, from one plausible word. The map
is now `Teleport` and `Dash` only, and `--map` prints all fourteen so the next
addition is inspected rather than inferred.

RESULT, 2026-09-06: THE CLASS REFUSES THE TELEPORTS IT EXISTS FOR
--------------------------------------------------------------------
Four clips whose agent has a teleport, agent from the ingest tag, cast from the
tray, track built here. `--steps` gives the largest step in the 3 s after each
teleport cast -- the first measurement anywhere of what a teleport LOOKS LIKE
on this widget with the cast timed:

    yoru     GATECRASH          4.6 px      6.3 px
    omen     Shrouded Step     38.5 px     40.1 px
    omen     From the Shadows   1.0 px     (clip ends 18 steps in)
    veto     Crosscut          65.0 px      6.8 px
    chamber  Rendezvous       323.8 px

    median 38.5 px, max 323.8, and 1 of 8 reaches TELEPORT_PX

**`track.TELEPORT_PX` is 200 widget px and it is far too high.** Its own
comment says what it is -- *"the widget is ~465 px across, so half of it in one
sample is not walking"* -- a bound on what is IMPOSSIBLE, never a measurement
of what a teleport covers. Against `admits`, at 15 Hz where a walker is allowed
3.0 px:

    yoru gatecrash      4.6 px   REFUSED  too far to walk, too near to teleport
    omen shrouded step 38.5 px   REFUSED  too far to walk, too near to teleport
    omen shrouded step 40.1 px   REFUSED  too far to walk, too near to teleport
    veto crosscut      65.0 px   REFUSED  too far to walk, too near to teleport
    chamber rendezvous 323.8 px  admitted  teleport

**`walker_teleport` refuses three of the four real teleports it was created to
admit**, and the default gate (4.8 px per step) refuses them too. Both gates
destroy the same events, and the dead zone between the walk ceiling and
`TELEPORT_PX` is where every SHORT teleport lives. That also explains item 1's
puzzling `+835`: the teleport branch almost never fires on a real teleport, so
what it recovered on a whole session was mostly long phantoms.

**So the cast has to license the STEP, not merely select a class that then
refuses it.** `filter_track` now takes span-conditional motion for that, but
the class to put in a span cannot be `walker_teleport` as currently defined.
Fixing `TELEPORT_PX` from these numbers is the obvious move and is NOT taken
here: n is 8 casts on 4 solo clips, and a constant refitted on 8 observations
to a value that admits them is the degenerate-crop mistake in a new costume.

**Two limits this run establishes about the tray as the licence source:**

* **a two-part teleport drops on PLACEMENT, not on traversal.** Yoru's two
  GATECRASH casts are followed by 4.6 and 6.3 px -- the player placed the gate and did
  not travel within 3 s. Chamber's Rendezvous, also two-part, DID show its
  323.8 px, so the window happened to catch the recall. The tray times the
  first half of a two-part ability and the jump belongs to the second, and no
  fixed window fixes that in general;
* **the ultimate is invisible here as predicted.** Omen's From the Shadows
  registered a drop only because the corpus is `infinite-abilities`; slot X
  draws pips, and this file's own caveat about it stands.

The corpus problem, stated rather than worked around
------------------------------------------------------
This needs one session with THREE things at once: a known agent, a readable
tray, and a position track. The store has no such session by default --

* the five sessions with an `l1/minimap` table record no agent at all;
* the 26 demo clips name the agent in their ingest tags and have a tray, but
  have no HUD L1, so `segment` has no spans and the minimap stage refuses.

So the track is built HERE, directly off the video with the shipped
`self_rings`/`pick_self`/`filter_track`, rather than read from L1. That is a
prototype measuring, not a stage: nothing is stored, and the numbers are not
comparable to the L1 census, which samples on active spans.

The demo clips are also `custom-game infinite-abilities`, which is a caveat
with a measurable consequence -- a charge that refills instantly may never show
the drop `ability_hud.casts` keys on. The run reports how many casts it saw, so
a null result reads as "no evidence" rather than "no teleports".
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import ability_hud
    import ability_reference as aref
from reticle import track                                          # noqa: E402
from reticle.decode import sample_at                               # noqa: E402
from reticle import geometry as _G                                  # noqa: E402
from reticle.minimap import (RUN_PX, filter_track, floor_mask,     # noqa: E402
                             minimap_roi_px, pick_self, self_rings,
                             widget_scale)
from reticle.profiles import get_profile                           # noqa: E402
from reticle.store import Store                                    # noqa: E402

STORE = pathlib.Path.home() / "reticle-store"

#: `functions` word -> motion class. Ordered: the first match wins, so an
#: ability that both teleports and dashes is treated as the more permissive
#: thing it can do.
#:
#: **`Displacement` is deliberately NOT here, and leaving it in was a real
#: defect for one run.** The field describes what an ability does to ANYONE,
#: not to its caster, so `Displacement` licensed a jump for Astra's Gravity
#: Well (`Cripple Displacement`), Breach's Rolling Thunder, Deadlock's
#: Annihilation and Miks' Bassquake -- four abilities that move ENEMIES and
#: leave the caster exactly where they were. A gate opened by those is a gate
#: opened for a phantom, which is the precise failure this whole entry exists
#: to prevent. `Dash` alone yields the five self-dashes and catches Raze's
#: Blast Pack anyway, since it is tagged `Dash Displacement`.
FUNCTION_CLASS = [("Teleport", "walker_teleport"),
                  ("Dash", "walker_dash")]


def class_map() -> dict[tuple[str, str], tuple[str, str]]:
    """(agent, slot) -> (motion class, ability name), off the stored reference."""
    out = {}
    for agent, d in aref.load()["agents"].items():
        for ab in d.get("abilities") or []:
            fn = ab.get("functions") or ""
            key = ab.get("key")
            if not key:
                continue
            for word, cls in FUNCTION_CLASS:
                if word in fn:
                    out[(agent.lower(), key)] = (cls, ab["name"])
                    break
    return out


def tagged_agent(sid: str) -> str | None:
    """The agent from the ingest tags, or None. Ground truth, recorded for
    another purpose long before this question existed."""
    f = STORE / "manifests" / f"{sid}.json"
    tags = [t.lower() for t in (json.loads(f.read_text(encoding="utf-8")).get("tags") or [])]
    known = {a.lower() for a in aref.load()["agents"]}
    hit = [t for t in tags if t in known]
    return hit[0] if len(hit) == 1 else None


def self_track(sid: str, hz: float):
    """(t_ms, x, y) at `hz`, with None for a frame the self ring was not found.

    The shipped primitives, in the shipped order -- `self_rings` for candidates,
    `pick_self` for nearest-to-previous. A None row is what `filter_track` reads
    as a hole, so it is carried rather than dropped.
    """
    store = Store()
    man = store.read_manifest(sid)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
    sc = widget_scale(x1 - x0)
    g = _G.path_of(sid, STORE)
    if g is None or not g.is_file():
        return None, None, None
    floor = floor_mask(np.load(g, allow_pickle=True)["static"])

    dur = float(src["duration_ms"])
    step_ms = 1000.0 / hz
    times = [i * step_ms for i in range(int(dur / step_ms))]
    rows, prev = [], None
    for smp in sample_at(src["path"], times, float(src["fps"])):
        crop = smp.frame[y0:y1, x0:x1]
        p = pick_self(self_rings(crop, floor), prev, step_ms, sc)
        rows.append((smp.t_ms, None, None) if p is None else (smp.t_ms, p[0], p[1]))
        prev = p
    return rows, sc, step_ms


def jumps(pts, sc: float) -> list[tuple[float, float]]:
    """(t_ms, distance) for every step at or beyond teleport distance.

    Measured between CONSECUTIVE OBSERVATIONS, before any filtering: the whole
    question is which of these the filter should have kept, so filtering them
    out first would answer it by assumption.
    """
    out = []
    obs = [p for p in pts if p[1] is not None]
    for a, b in zip(obs, obs[1:]):
        d = float(np.hypot(b[1] - a[1], b[2] - a[2]))
        if d >= track.TELEPORT_PX * sc:
            out.append((b[0], d))
    return out


def cross(sid: str, hz: float, window_s: float, step_s: float = 0.5) -> dict:
    agent = tagged_agent(sid)
    if agent is None:
        return {"error": "no single agent tag"}
    cm = class_map()

    ts, counts, clean = ability_hud.scan(sid, step_s=step_s)
    if not len(ts):
        return {"error": "tray unreadable"}
    ev = ability_hud.casts(ts, counts, clean)
    tele = [(t, slot) for t, slot, *_ in ev
            if cm.get((agent, slot), ("", ""))[0] == "walker_teleport"]

    pts, sc, _step = self_track(sid, hz)
    if pts is None:
        return {"error": "no geometry"}
    js = jumps(pts, sc)

    # A jump is LICENSED if a teleport cast opened a window that contains it.
    lic = [j for j in js if any(t <= j[0] / 1000.0 <= t + window_s for t, _ in tele)]
    used = {t for t, _ in tele
            if any(t <= j[0] / 1000.0 <= t + window_s for j in js)}
    return {"agent": agent, "casts": len(ev), "tele_casts": len(tele),
            "obs": sum(1 for p in pts if p[1] is not None), "frames": len(pts),
            "jumps": len(js), "licensed": len(lic),
            "casts_with_jump": len(used), "scale": sc,
            "abilities": sorted({cm.get((agent, s), ("", s))[1] for _t, s in tele})}


def cast_steps(sid: str, hz: float, window_s: float, step_s: float = 0.5):
    """Per teleport cast, the LARGEST step in the window it opens.

    The question `--teleport-corpus` could not answer: `track.TELEPORT_PX` is
    200 widget px, chosen as *"the widget is ~465 px across, so half of it in
    one sample is not walking"* -- a bound on what is IMPOSSIBLE, never a
    measurement of what a teleport actually covers. With the agent known and
    the cast timed, the distribution can be read off directly.
    """
    agent = tagged_agent(sid)
    cm = class_map()
    ts, counts, clean = ability_hud.scan(sid, step_s=step_s)
    ev = ability_hud.casts(ts, counts, clean)
    pts, sc, _ = self_track(sid, hz)
    if pts is None:
        return []
    obs = [q for q in pts if q[1] is not None]
    steps = [(b[0], float(np.hypot(b[1] - a[1], b[2] - a[2])))
             for a, b in zip(obs, obs[1:])]
    out = []
    for t, slot, *_ in ev:
        cls, name = cm.get((agent, slot), (None, None))
        if cls != "walker_teleport":
            continue
        win = [d for tm, d in steps if t <= tm / 1000.0 <= t + window_s]
        out.append((sid, agent, name, slot, t, max(win) if win else None,
                    len(win), sc))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?")
    ap.add_argument("--hz", type=float, default=15.0)
    ap.add_argument("--window", type=float, default=3.0,
                    help="seconds after a cast in which a jump is licensed")
    ap.add_argument("--teleport-corpus", action="store_true",
                    help="every tagged session whose agent has a teleport")
    ap.add_argument("--steps", action="store_true",
                    help="per teleport cast, the largest step it was followed by")
    ap.add_argument("--map", action="store_true",
                    help="print the derived (agent, slot) -> class map and stop")
    a = ap.parse_args(argv)

    cm = class_map()
    if a.map:
        print(f"{len(cm)} abilities carry a motion class, derived from "
              f"`ability_reference` `functions`\n")
        print(f"{'agent':<12}{'slot':<6}{'class':<18}ability")
        for (ag, slot), (cls, name) in sorted(cm.items()):
            print(f"{ag:<12}{slot:<6}{cls:<18}{name}")
        return 0

    if a.teleport_corpus:
        tele_agents = {ag for (ag, _s), (c, _n) in cm.items()
                       if c == "walker_teleport"}
        sids = []
        for f in sorted((STORE / "manifests").glob("*.json")):
            ag = tagged_agent(f.stem)
            if ag in tele_agents:
                sids.append(f.stem)
        if not sids:
            raise SystemExit("no tagged session plays a teleporting agent")
        print(f"teleport agents in the store: {len(sids)} session(s), "
              f"window {a.window:g}s, track at {a.hz:g} Hz\n")
        print(f"{'session':<14}{'agent':<11}{'casts':>6}{'tele':>6}{'obs':>7}"
              f"{'jumps':>7}{'licensed':>9}{'casts w/ jump':>14}")
        tot = collections.Counter()
        for sid in sids:
            r = cross(sid, a.hz, a.window)
            if "error" in r:
                print(f"{sid:<14}{'':<11}{r['error']}")
                continue
            for k in ("tele_casts", "jumps", "licensed", "casts_with_jump"):
                tot[k] += r[k]
            print(f"{sid:<14}{r['agent']:<11}{r['casts']:>6}{r['tele_casts']:>6}"
                  f"{r['obs']:>7}{r['jumps']:>7}{r['licensed']:>9}"
                  f"{r['casts_with_jump']:>14}")
        print(f"\n{'POOLED':<14}{'':<11}{'':>6}{tot['tele_casts']:>6}{'':>7}"
              f"{tot['jumps']:>7}{tot['licensed']:>9}{tot['casts_with_jump']:>14}")
        if tot["jumps"]:
            print(f"\n  jumps a cast licenses:  {tot['licensed']}/{tot['jumps']} "
                  f"({tot['licensed'] / tot['jumps'] * 100:.0f}%) -- the rest are "
                  f"phantoms, or teleports the tray did not show")
        if tot["tele_casts"]:
            print(f"  casts a jump confirms:  {tot['casts_with_jump']}/"
                  f"{tot['tele_casts']} ({tot['casts_with_jump'] / tot['tele_casts'] * 100:.0f}%)"
                  f" -- the rest teleported nowhere the widget could show, or "
                  f"the track lost the player")
        return 0

    if a.steps:
        tele_agents = {ag for (ag, _s), (c, _n) in cm.items()
                       if c == "walker_teleport"}
        rows = []
        for f in sorted((STORE / "manifests").glob("*.json")):
            if tagged_agent(f.stem) in tele_agents:
                rows += cast_steps(f.stem, a.hz, a.window)
        print(f"largest step in the {a.window:g}s after each teleport cast, "
              f"track at {a.hz:g} Hz\n")
        print(f"{'session':<14}{'agent':<10}{'ability':<18}{'slot':<5}"
              f"{'t':>7}{'max step':>10}{'as x RUN_PX':>13}{'steps':>7}")
        big = 0
        for sid, ag, name, slot, t, d, n, sc in rows:
            if d is None:
                print(f"{sid:<14}{ag:<10}{name:<18}{slot:<5}{t:>7.1f}"
                      f"{'--':>10}{'':>13}{n:>7}")
                continue
            # A step's speed ceiling for a walker is RUN_PX * scale * dt.
            walk = RUN_PX * sc / a.hz
            big += d >= track.TELEPORT_PX * sc
            print(f"{sid:<14}{ag:<10}{name:<18}{slot:<5}{t:>7.1f}{d:>10.1f}"
                  f"{d / walk:>13.1f}{n:>7}")
        got = [d for *_x, d, _n, _sc in rows if d is not None]
        if got:
            got.sort()
            print(f"\n{len(got)} casts with a track: max step median "
                  f"{got[len(got) // 2]:.1f} px, max {got[-1]:.1f} px")
            print(f"  reaching TELEPORT_PX ({track.TELEPORT_PX:g} widget px): "
                  f"{big}/{len(got)}")
        return 0

    if not a.session:
        ap.error("give a session, --teleport-corpus, --steps, or --map")
    r = cross(a.session, a.hz, a.window)
    if "error" in r:
        raise SystemExit(r["error"])
    print(f"{a.session}: {r['agent']}, {r['obs']}/{r['frames']} frames with a "
          f"self ring, widget scale {r['scale']:.2f}")
    print(f"  casts read from the tray: {r['casts']}, of which "
          f"{r['tele_casts']} are teleports ({', '.join(r['abilities']) or '--'})")
    print(f"  jumps >= {track.TELEPORT_PX:g} widget px: {r['jumps']}, "
          f"licensed by a cast within {a.window:g}s: {r['licensed']}")
    print(f"  teleport casts followed by a jump: {r['casts_with_jump']}"
          f"/{r['tele_casts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
