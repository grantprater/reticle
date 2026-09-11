"""WHO each roster slot is, from the top bar, accumulated until confident.

The top bar is the cheapest identity surface in the game: it is drawn every
frame of every round, it needs no Tab press, and it holds all ten agents. So
identity is not a special pass -- it rides whatever decode is already
happening, exactly as `roster` and `ping` do, and every scan that is not
testing one specific thing should be reading it.

**Composition, not pixels.** `minimap_portrait` established that colour
composition transfers across surfaces where pixel matching scores below chance,
and a histogram is layout-free -- which is also why the enemy bar being mirrored
costs nothing here.

**One frame is not an answer; the MARGIN is.** Measured on Lotus
`7010b3d62460`, 67 contributing frames of 90 sampled, official art only, no
session mining and no labels, against the 29-agent gallery:

    slot   answer     margin   truth
    2      Phoenix     0.153    correct
    1      Sage        0.138    correct
    4      Cypher      0.132    correct
    0      --          0.054    refused; truth Chamber, and Chamber is the
                                rival it could not be separated from
    3      --          0.013    refused; truth Brimstone

The margin separates them completely, so the gate is the margin and a slot
below it stays `None` with a reason rather than guessing. `MARGIN_MIN` is a
PROVISIONAL cut resting on one lineup of five slots -- every verdict carries
its margin so a real cut can be fitted when more lineups are known.

**The margin is measured against the ASSIGNMENT, not the raw ordering** -- see
`adjudicate` for the rule. Over 190 slots in 19 sessions, old against new on
IDENTICAL score matrices, refusals went from
[metric:lineup/assignment-margin#refused_before=82] to
[metric:lineup/assignment-margin#refused=73]:
[metric:lineup/assignment-margin#gained=11] slots named where the constraint
had already broken the tie, and [metric:lineup/assignment-margin#lost=2]
UNNAMED that the old rule had named. The two losses are the better half of the
result. Both are `043bafca271a` enemy slots 0 and 4, which both look most like
Breach; the old margin scored Breach against its own runner-up, cleared the
gate on that, and then named slot 0 *Raze* -- a name justified by a different
agent's evidence. Nothing could see it until the alternative had to be one the
constraint permits.

Coverage is not the result to read here. Nine of the eleven newly named sit
within 0.03 of `MARGIN_MIN`, and no newly named slot has a recorded truth to
check it against, so the honest summary is that the rule stopped measuring the
wrong quantity -- not that identity coverage is solved.

Owns [owns:agent-from-slot] and [owns:player-agent].
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import cv2
import numpy as np

from .roster import ART_FRAC, N_SLOTS, alive_counts, roster_rois
from .track import assign

LINEUP_VERSION = "lineup-0.3.0"

#: The three official renderings of an agent. They are independent drawings of
#: one thing, so their scores are summed rather than chosen between.
SURFACES = ("agent_icon", "killfeed_portrait", "minimap_portrait")

#: Provisional. See the module docstring: five slots, one session.
MARGIN_MIN = 0.07


def _agent_name(path: str, surface: str) -> str:
    # `KAY_O_agent_icon.png` -- strip the SUFFIX, never split on "_".
    return os.path.basename(path)[: -len(f"_{surface}.png")]


def _composition(bgr, mask=None):
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root / "prototypes") not in sys.path:
        sys.path.insert(0, str(root / "prototypes"))
    from minimap_portrait import composition
    return composition(bgr, mask)


def load_lineup(session: str, store) -> dict | None:
    """The stored lineup verdict for a session, or None when never read."""
    import json
    f = Path(store) / "lineups" / f"{session}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def load_gallery(store) -> dict[str, list[np.ndarray]]:
    """Every agent's official art as composition histograms, by agent name."""
    art = Path(store) / "reference" / "assets" / "agents"
    out: dict[str, list[np.ndarray]] = {}
    for surface in SURFACES:
        for f in sorted(glob.glob(str(art / f"*_{surface}.png"))):
            im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
            if im is None:
                continue
            mask = (im[:, :, 3] > 128) if im.shape[2] == 4 else None
            out.setdefault(_agent_name(f, surface), []).append(
                _composition(im[:, :, :3], mask))
    return out


def slot_crops(crop: np.ndarray) -> list[np.ndarray]:
    """The five portrait cells of one roster bar, left to right.

    Same split `roster.slot_detail` uses, so a slot means the same thing to the
    reader that counts the living and the one that names them.
    """
    if crop is None or crop.size == 0:
        return []
    art = crop[: max(1, int(crop.shape[0] * ART_FRAC))]
    if art.size == 0:
        return []
    w = art.shape[1] / float(N_SLOTS)
    return [art[:, int(i * w):int((i + 1) * w)] for i in range(N_SLOTS)]


def adjudicate(scores, names: list[str], frames: int, side: str = "ally",
               margin_min: float = MARGIN_MIN) -> list[dict]:
    """One row per slot: the agent, its margin, and whether to believe it.

    Pure over the per-frame (slot, agent) matrix, so a stored lineup can be
    re-adjudicated without opening the capture again.

    The five slots are five DIFFERENT agents, so this is an assignment and not
    five arg-maxes -- the same constraint the tracker uses on icons, for the
    same reason. A slot under the margin is `None` WITH its best guess kept
    beside it, because an unread value must say what it is.

    **Per SIDE, and never across the match**: [domain:rounds/agent-uniqueness].
    Both teams may field the same agent, so naming one on this side says
    nothing about the other -- a ten-slot assignment would have named 11
    refused slots wrongly across the stored lineups.

    **The margin is measured against the assignment, not against the raw
    ordering.** It is the optimal assignment's total score minus the best total
    attainable when this slot is FORBIDDEN its agent, so the alternative it is
    separated from is one the uniqueness constraint permits, and the
    displacement that alternative forces on the other four slots is paid for in
    the margin.

    The version this replaces compared `order[0]` with `order[1]` on the raw
    per-slot ordering, computed WITHOUT the assignment made two lines above it.
    Where the runner-up was near-tied but taken by another slot, the constraint
    had already resolved the tie and the slot was refused anyway -- 12 of 79
    refusals across 19 stored lineups. The count read as thin evidence and was
    a measurement taken in the wrong place.

    `best_guess` is the assignment's pick for the same reason. Reporting an
    argmax the constraint has already rejected is the original fault wearing a
    different field name.
    """
    s = np.asarray(scores, dtype=float)
    cost = [[-float(v) for v in row] for row in s]
    picked = assign(cost)
    best_total = sum(float(s[i, j]) for i, j in enumerate(picked) if j >= 0)
    out = []
    for i, j in enumerate(picked):
        margin, rival = 0.0, None
        if j >= 0:
            # Forbidding one cell and re-solving gives the best assignment in
            # which THIS slot differs -- the maximum over every alternative at
            # once, for one solve rather than one per candidate agent.
            blocked = [row[:] for row in cost]
            blocked[i][j] = float("inf")
            other = assign(blocked)
            margin = best_total - sum(float(s[k, c])
                                      for k, c in enumerate(other) if c >= 0)
            rival = names[other[i]] if other[i] >= 0 else None
        ok = j >= 0 and margin >= margin_min
        out.append({
            "slot": i, "side": side,
            "agent": names[j] if ok else None,
            "best_guess": names[j] if j >= 0 else names[int(np.argmax(s[i]))],
            "rival": rival,
            "score": round(float(s[i, j]) if j >= 0 else 0.0, 4),
            "margin": round(margin, 4),
            "frames": frames,
            "reason": None if ok else
                      f"margin {margin:.3f} below {margin_min} -- "
                      + (f"not separated from {rival}" if rival
                         else "no assignment"),
        })
    return out


class Lineup:
    """Scores per (slot, agent), summed over however many frames arrive.

    Accumulating SCORES rather than votes is deliberate: an argmax per frame
    throws away how close the runner-up was, and the closeness is the only
    thing here that knows whether the answer is worth having.
    """

    def __init__(self, gal: dict[str, list[np.ndarray]]):
        self.names = sorted(gal)
        self.gal = gal
        self.scores = {"ally": np.zeros((N_SLOTS, len(self.names))),
                       "enemy": np.zeros((N_SLOTS, len(self.names)))}
        self.frames = 0
        # A SECOND witness, and a different surface: the portrait inside the
        # self icon. Fed from wherever self icons are already found -- it is
        # not detected again here.
        self.self_scores = np.zeros(len(self.names))
        self.self_n = 0
        # A THIRD witness, and the only one that names the player's agent
        # outright rather than by elimination.
        self.tray_votes: dict[str, int] = {}
        self.tray_frames = 0
        self._glyphs = None

    def add(self, frame: np.ndarray, profile, w: int, h: int) -> bool:
        """Accumulate one frame, but ONLY from a side that is fully alive.

        **The bar packs.** `roster.alive_from_detail` reads the living as a
        contiguous run anchored at the scoreline edge, which means a dead
        player is dropped and the survivors SHIFT -- so slot 2 is a different
        agent before and after a death, and accumulating per fixed index across
        a match silently averages several agents into one cell. Five alive is
        the only state in which the index is an identity, and it is the common
        one: it holds at the start of every round.
        """
        rois = dict(zip(("ally", "enemy"), roster_rois(profile, w, h)))
        alive = dict(zip(("ally", "enemy"), alive_counts(frame, profile, w, h)))
        seen = False
        for side, roi in rois.items():
            if roi is None or alive.get(side) != N_SLOTS:
                continue
            x0, y0, x1, y1 = roi
            for i, sub in enumerate(slot_crops(frame[y0:y1, x0:x1])):
                if sub.size == 0:
                    continue
                hq = self._composition(sub)
                for j, n in enumerate(self.names):
                    self.scores[side][i, j] += sum(
                        float(np.minimum(hq, g).sum()) for g in self.gal[n])
                seen = True
        self.frames += bool(seen)
        return seen

    _composition = staticmethod(_composition)

    def add_self(self, appearance) -> None:
        """One more look at the player's own icon, as a composition histogram.

        Takes the vector rather than the crop because the round pipeline has
        already computed it for association -- `composition()` of the icon
        interior is the same feature this needs, and computing it twice would
        be paying for one thing at two call sites.
        """
        hq = np.asarray(appearance, dtype=np.float32)
        if not hq.size:
            return
        for j, n in enumerate(self.names):
            self.self_scores[j] += sum(float(np.minimum(hq, g).sum())
                                       for g in self.gal[n])
        self.self_n += 1

    def add_tray(self, frame, store, margin_min: float = MARGIN_MIN) -> None:
        """Vote from the player's own ability tray, when it is readable."""
        if self._glyphs is None:
            self._glyphs = load_glyph_gallery(store)
        agent, _, margin = tray_vote(frame, self._glyphs)
        self.tray_frames += 1
        if agent and margin >= margin_min:
            self.tray_votes[agent] = self.tray_votes.get(agent, 0) + 1

    def tray_verdict(self):
        """`(agent, votes, total_votes)` -- the tray's own answer, unmixed."""
        if not self.tray_votes:
            return None, 0, 0
        total = sum(self.tray_votes.values())
        agent = max(self.tray_votes, key=self.tray_votes.get)
        return agent, self.tray_votes[agent], total

    def player(self, side: str = "ally", margin_min: float = MARGIN_MIN) -> dict:
        """Which slot the player is, from the top bar AND the self icon.

        **Neither witness is confident alone and together they are**, which is
        the whole argument for corroborating rather than picking a best
        detector. On Lotus the self icon ranks Phoenix 2nd of 29 at a margin of
        0.045 -- refused on its own -- but the top bar proposes only five
        candidates, and among those five Phoenix wins by 0.098.

        The scores are NOT summed. The top bar decides WHO is on the team and
        the self icon decides WHICH of them is holding the camera; they answer
        different questions and pooling them would let a confident answer to
        one paper over silence on the other. Disagreement is kept.
        """
        tray_agent, tray_votes, tray_total = self.tray_verdict()
        if not self.self_n and not tray_agent:
            return {"slot": None, "agent": None,
                    "reason": "no self icon and no readable tray",
                    "witnesses": {}}
        rows_all = self.verdict(side, margin_min=0.0)
        gated_all = self.verdict(side, margin_min=margin_min)
        # THE TRAY FIRST when it has spoken: it names the agent outright, where
        # the self icon only ranks the five the top bar proposes. If that agent
        # is on the team, the slot holding it is the player and no elimination
        # is needed.
        if tray_agent:
            hit = next((r for r in rows_all if r["agent"] == tray_agent), None)
            if hit is not None:
                return {
                    "slot": hit["slot"], "agent": tray_agent,
                    "margin": None, "self_frames": self.self_n,
                    "decided_by": "ability_tray",
                    "witnesses": {
                        "tray": {"agent": tray_agent,
                                 "votes": f"{tray_votes}/{tray_total}",
                                 "frames_offered": self.tray_frames},
                        "top_bar": {"agent": gated_all[hit["slot"]]["agent"],
                                    "margin": gated_all[hit["slot"]]["margin"]},
                    },
                    # ABSTAINED is not DISAGREED. The top bar refusing a slot
                    # for want of margin says nothing against the tray, and
                    # collapsing the two into a boolean would report a conflict
                    # where there is only silence.
                    "agree": ("agrees" if gated_all[hit["slot"]]["agent"] == tray_agent
                              else "abstained" if gated_all[hit["slot"]]["agent"] is None
                              else "DISAGREES"),
                    "reason": None,
                }
        if not self.self_n:
            return {"slot": None, "agent": None,
                    "reason": f"tray says {tray_agent}, which no {side} slot "
                              f"proposes, and there is no self icon",
                    "witnesses": {"tray": {"agent": tray_agent}}}
        s = self.self_scores / self.self_n
        by_name = {n: float(s[j]) for j, n in enumerate(self.names)}
        rows = rows_all                                # ungated: candidates only
        ranked = sorted(((by_name.get(r["agent"], 0.0), r) for r in rows),
                        key=lambda t: -t[0])
        best, runner = ranked[0], ranked[1] if len(ranked) > 1 else (0.0, None)
        margin = best[0] - runner[0]
        gated = gated_all
        top_bar_named = gated[best[1]["slot"]]["agent"]
        ok = margin >= margin_min
        return {
            "slot": best[1]["slot"] if ok else None,
            "agent": best[1]["agent"] if ok else None,
            "margin": round(margin, 4),
            "self_frames": self.self_n,
            "decided_by": "self_icon_among_top_bar_candidates",
            "witnesses": {
                "top_bar": {"agent": top_bar_named,
                            "margin": gated[best[1]["slot"]]["margin"]},
                "self_icon": {"agent": max(by_name, key=by_name.get),
                              "rank_of_pick": 1 + sorted(
                                  by_name, key=lambda n: -by_name[n]).index(
                                      best[1]["agent"])},
            },
            "agree": ("agrees" if top_bar_named == best[1]["agent"]
                      else "abstained" if top_bar_named is None else "DISAGREES"),
            "reason": None if ok else
                      f"margin {margin:.3f} below {margin_min} across the "
                      f"{side} slots",
        }

    def mean_scores(self, side: str) -> np.ndarray:
        """The (slot, agent) evidence, per frame. THE observation this stores.

        Kept separate from `verdict` because the verdict is adjudication over
        it, and adjudication that cannot be recomputed from a stored
        observation is adjudication nobody can revisit. Changing the margin
        rule cost a seven-minute decode of nineteen sessions precisely because
        this matrix was thrown away and only the verdict was written down.
        """
        return self.scores[side] / max(self.frames, 1)

    def verdict(self, side: str, margin_min: float = MARGIN_MIN) -> list[dict]:
        """This side's slots, adjudicated. See `adjudicate`."""
        return adjudicate(self.mean_scores(side), self.names, self.frames,
                          side, margin_min)

    def stored_scores(self) -> dict:
        """The observation to write beside the verdict, for `adjudicate`.

        Ten rows of 29 numbers. It costs about 3 KB per session and buys the
        next change to the margin rule the decode this one had to pay.
        """
        return {"names": list(self.names),
                **{side: [[round(float(v), 5) for v in row]
                          for row in self.mean_scores(side)]
                   for side in ("ally", "enemy")}}


class LineupReader:
    """`passes.Reader` that names the ten agents while some other pass runs.

    **Identity is not a special pass.** The top bar is drawn every frame, so
    this needs no decode of its own -- it joins whatever scan is happening at
    a tenth of a hertz, which over a 40 minute capture is a couple of hundred
    spaced samples, far more than the 90 the answer converged on. That is why
    it should be on by DEFAULT: a scan that is not testing one specific thing
    has no reason to skip it and no cost for keeping it.

    The scores accumulate and the verdict is taken at `finish`, so a slot that
    is never separated stays unnamed rather than being decided by whichever
    frame happened to be last.
    """

    def __init__(self, profile, wh, store, name="lineup", hz=0.1, spans=None):
        self.name, self.hz, self.spans = name, hz, spans
        self.profile = profile
        self.w, self.h = wh
        self.store = store
        self.state = Lineup(load_gallery(store))

    def feed(self, smp) -> None:
        self.state.add(smp.frame, self.profile, self.w, self.h)
        # The same frame carries the player's own tray. Reading it here costs
        # nothing extra and is the one witness that names the agent outright.
        self.state.add_tray(smp.frame, self.store)

    def finish(self):
        agent, votes, total = self.state.tray_verdict()
        return [{"version": LINEUP_VERSION, "frames": self.state.frames,
                 "margin_min": MARGIN_MIN,
                 "sides": {side: self.state.verdict(side)
                           for side in ("ally", "enemy")},
                 "tray": {"agent": agent, "votes": votes, "total": total,
                          "frames_offered": self.state.tray_frames},
                 "player": self.state.player("ally"),
                 "scores": self.state.stored_scores()}]


def read_session(session: str, store, frames: int = 90, cap=None):
    """Sample spaced frames across a capture and return both lineups.

    Spaced rather than consecutive: neighbouring frames are the same picture,
    so they add cost and no evidence. Spread over the whole capture the sample
    also crosses round boundaries, agent deaths and menu overlays, and the
    accumulation is what survives them.
    """
    import json
    manifest = json.loads((Path(store) / "manifests" / f"{session}.json")
                          .read_text(encoding="utf-8"))
    from .profiles import get_profile
    profile = get_profile(manifest["source_profile"])
    src = manifest["source"]
    own = cap is None
    cap = cv2.VideoCapture(src["path"]) if own else cap
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    state = Lineup(load_gallery(store))
    try:
        for fi in np.linspace(total * 0.05, total * 0.95, frames).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fi))
            ok, fr = cap.read()
            if ok:
                state.add(fr, profile, src["width"], src["height"])
                state.add_tray(fr, store)
    finally:
        if own:
            cap.release()
    return state


def main(argv=None):
    """Name the ten agents in a capture from its top bar.

        python -m reticle.lineup SESSION [--frames N] [--write]
    """
    import argparse
    import json
    from .store import Store
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("session")
    ap.add_argument("--frames", type=int, default=90)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    store = Store().root
    state = read_session(args.session, store, args.frames)
    rows = {side: state.verdict(side) for side in ("ally", "enemy")}
    player = state.player("ally")
    agent, votes, total = state.tray_verdict()
    print(f"{args.session}: {state.frames} frames sampled")
    print(f"  tray   {agent or '--'} ({votes}/{total} votes over "
          f"{state.tray_frames} frames offered)")
    print(f"  PLAYER {player.get('agent') or '--'}"
          + (f", ally slot {player['slot']}" if player.get("slot") is not None else "")
          + f"   decided by {player.get('decided_by', '--')}"
          + (f"   [top bar agrees: {player.get('agree')}]"
             if player.get("witnesses", {}).get("top_bar") else "")
          + (f"   ({player['reason']})" if player.get("reason") else ""))
    for side in ("ally", "enemy"):
        named = sum(1 for r in rows[side] if r["agent"])
        print(f"  {side} ({named}/{N_SLOTS} named)")
        for r in rows[side]:
            if r["agent"]:
                print(f"     slot {r['slot']}  {r['agent']:10} "
                      f"margin {r['margin']:.3f}")
            else:
                print(f"     slot {r['slot']}  {'--':10} "
                      f"margin {r['margin']:.3f}  best guess {r['best_guess']}"
                      f"  ({r['reason']})")
    if args.write:
        out = Path(store) / "lineups" / f"{args.session}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"version": LINEUP_VERSION,
                                   "session": args.session,
                                   "frames": state.frames,
                                   "margin_min": MARGIN_MIN,
                                   "sides": rows,
                                   "tray": {"agent": agent, "votes": votes,
                                            "total": total,
                                            "frames_offered": state.tray_frames},
                                   "player": player,
                                   "scores": state.stored_scores()},
                                  indent=2), encoding="utf-8")
        print(f"  wrote {out}")
    return 0




#: Asset filenames cannot hold "/", so the art is `KAY_O` where the reference
#: is `KAY/O`. One agent, two spellings, and nothing else differs.
ASSET_TO_AGENT = {"KAY_O": "KAY/O"}


def abilities_for(agent: str, store) -> dict[str, str]:
    """`{slot key: ability name}` for one agent, from the official reference.

    The slot keys are the same C/Q/E/X the HUD tray is drawn in, so this is the
    whole of `agent:ability` naming once the agent is known -- no matching, no
    labels, no threshold. The passive (no key) is dropped: it is not castable
    and has no tray slot.
    """
    import json
    ref = json.loads((Path(store) / "reference" / "abilities.json")
                     .read_text(encoding="utf-8"))["agents"]
    entry = ref.get(ASSET_TO_AGENT.get(agent, agent))
    if not entry:
        return {}
    return {a["key"]: a["name"] for a in entry.get("abilities", [])
            if a.get("key")}


def ability_label(agent: str, key: str, store) -> str | None:
    """`phoenix:blaze` for (Phoenix, C), or None when either half is unknown.

    The form is `labels/ability_categories.json`'s -- lowercase `agent:ability`
    -- so a named cast and a hand-labelled one are the same string.
    """
    if not agent or not key:
        return None
    name = abilities_for(agent, store).get(key)
    return f"{agent.lower()}:{name.lower()}" if name else None


# ---------------------------------------------------------------------------
# The ability tray: the player's own four glyphs, and the strongest witness of
# the three -- large, unoccluded, and drawn every frame the HUD is up.
# ---------------------------------------------------------------------------

#: A glyph is a symbol with background around it, so a mask that fills most of
#: its cell has stopped being a glyph. This is STRUCTURE, not a cut fitted to an
#: answer, and it is the whole difference between the witness working and lying:
#: an absolute brightness threshold floods when the world behind the HUD is
#: bright, and on Lotus's sandy buy phase it filled 79-97% of every cell and
#: named the wrong agent at a margin that would have cleared any gate. With the
#: fill gate the same sessions vote 22/22 correct and refuse the rest.
GLYPH_FILL = (0.04, 0.45)

#: Tray cell, in source pixels. `prototypes/ability_hud` owns the geometry.
TRAY_TOP, TRAY_BOTTOM, TRAY_HALF_W = 974, 1031, 30


def _binary_shape(mask, size=48):
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    return cv2.resize(crop, (size, size),
                      interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def load_glyph_gallery(store) -> dict[str, dict[str, np.ndarray]]:
    """`{agent: {slot key: shape}}` from the official ability art."""
    import json
    root = Path(store)
    ref = json.loads((root / "reference" / "abilities.json")
                     .read_text(encoding="utf-8"))["agents"]
    art = root / "reference" / "assets" / "abilities"
    asset = {v: k for k, v in ASSET_TO_AGENT.items()}
    out: dict[str, dict[str, np.ndarray]] = {}
    for agent, entry in ref.items():
        stem = asset.get(agent, agent)
        per = {}
        for ab in entry.get("abilities", []):
            key, slot = ab.get("key"), ab.get("slot")
            if not key or not slot:
                continue
            im = cv2.imread(str(art / f"{stem}_{slot}.png"), cv2.IMREAD_UNCHANGED)
            if im is None:
                continue
            m = ((im[:, :, 3] > 96) if im.shape[2] == 4
                 else (cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) > 96))
            shape = _binary_shape(m)
            if shape is not None:
                per[key] = shape
        if per:
            out[agent] = per
    return out


def tray_shapes(frame: np.ndarray) -> dict[str, np.ndarray]:
    """The player's tray glyphs this frame, or fewer when the mask is unusable.

    Refusing a cell is the point: a flooded mask still produces a confident
    nearest neighbour, and confidence computed from garbage is worse than
    silence.
    """
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root / "prototypes") not in sys.path:
        sys.path.insert(0, str(root / "prototypes"))
    from ability_hud import SLOT_X0, SLOT_DX, SLOT_KEYS
    cell = (TRAY_BOTTOM - TRAY_TOP) * 2 * TRAY_HALF_W
    out = {}
    for i, key in enumerate(SLOT_KEYS):
        cx = SLOT_X0 + SLOT_DX * i
        patch = frame[TRAY_TOP:TRAY_BOTTOM, cx - TRAY_HALF_W:cx + TRAY_HALF_W]
        if patch.size == 0:
            continue
        mask = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) > 170
        if not GLYPH_FILL[0] <= mask.sum() / cell <= GLYPH_FILL[1]:
            continue
        shape = _binary_shape(mask)
        if shape is not None:
            out[key] = shape
    return out


def tray_vote(frame: np.ndarray, glyphs: dict[str, dict[str, np.ndarray]],
              min_slots: int = 2):
    """`(agent, score, margin)` from this frame's tray, or `(None, 0, 0)`.

    One slot is not an identification -- several agents share a circle -- so a
    frame offering fewer than `min_slots` readable glyphs abstains.
    """
    shapes = tray_shapes(frame)
    if len(shapes) < min_slots:
        return None, 0.0, 0.0
    scored = {}
    for agent, per in glyphs.items():
        common = [k for k in shapes if k in per]
        if not common:
            continue
        scored[agent] = sum(
            float(np.minimum(shapes[k], per[k]).sum()
                  / (np.maximum(shapes[k], per[k]).sum() + 1e-6))
            for k in common) / len(common)
    if len(scored) < 2:
        return None, 0.0, 0.0
    order = sorted(scored, key=lambda a: -scored[a])
    return order[0], scored[order[0]], scored[order[0]] - scored[order[1]]

if __name__ == "__main__":
    raise SystemExit(main())
