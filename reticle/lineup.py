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
`adjudication.identity.assign_side` for the rule. Over 190 slots in 19 sessions, old against new on
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

**The player's agent is the arbiter's.** `Lineup` gathers the tray's votes
and the self icon's scores as observations (`Lineup.player_witnesses`) and
combines neither. `identity.claims_from_lineup` makes each a claim on the
player entity, the arbiter decides, and `identity.player_identity` reads the
answer, with the slot bound to the ally row holding that agent. A tray that
outvoted a disagreeing self icon, as `Lineup.player` let it, is now a
disagreement with both names kept.

Owns [owns:agent-from-slot] and [owns:player-agent].
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import cv2
import numpy as np

from .roster import ART_FRAC, N_SLOTS, alive_counts, roster_rois
from .adjudication.identity import (SIDE_MARGIN_MIN, adjudicate_agent_identity,
                                    assign_side, claims_from_lineup,
                                    lineup_player_witnesses, player_entity,
                                    player_identity)

# 0.5.0 (2026-09-28): the file stores the player's witnesses raw
# (`player_witnesses`: the tray's votes per agent, the self icon's mean scores)
# in place of the tray's winner, and `player` is the arbiter's answer
# (`identity.player_identity`); `Lineup.player` no longer combines them.
LINEUP_VERSION = "lineup-0.5.0"

#: The three official renderings of an agent. They are independent drawings of
#: one thing, so their scores are summed rather than chosen between.
SURFACES = ("agent_icon", "killfeed_portrait", "minimap_portrait")

#: Provisional. See the module docstring: five slots, one session. The value
#: lives with the decision, in `adjudication.identity`.
MARGIN_MIN = SIDE_MARGIN_MIN


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
    """The stored lineup verdict for a session, or None when never read.

    **The identity verdict is DERIVED here when the file predates it.** The 19
    stored lineups were written before `agent_identity` existed and carry the
    same version stamp as a file that has it, so a consumer reading the key
    would fail on two thirds of the store while the stamp said current. The
    claims are pure over `sides` and `player`, which every file already holds,
    so this costs no decode and no rewrite -- and the artifact is never the
    only place the answer lives.

    **The scoreboard constrains it here too**, when the session's stored rows
    carry the verdicts the current reader would write
    (`version.SCOREBOARD_VERDICT_COMPATIBLE`): `identity.board_side_sets` decides each side's five agents
    and `identity.lineup_with_board` re-assigns the top bar over them, keeping
    the unconstrained verdict and every disagreement beside it.

    **`player` is the arbiter's answer**, `identity.player_identity` over the
    verdicts returned here; the file's own `player` stays as `stored_player`.
    A file whose verdicts hold no player entity (every one before
    `lineup-0.5.0`, and any keyed by another observation id) has its claims
    derived again from `sides` and its stored witnesses.

    **The self icon is read from its own stored rows** (`reticle self-icon`,
    `self_icon.stored_witness`) where the file holds no self-icon frame, which
    is every file written by a scan: no scan feeds `Lineup.add_self`. The
    claims are then derived again, and `self_icon_state` says which witness
    was used.
    """
    import json
    f = Path(store) / "lineups" / f"{session}.json"
    if not f.is_file():
        return None
    got = json.loads(f.read_text(encoding="utf-8"))
    got.setdefault("session", session)
    if "player" in got:
        got["stored_player"] = got.pop("player")
    attached = _attach_self_icon(got, session, store)
    if attached or not any(v.get("entity_id") == player_entity(session)
                           for v in got.get("agent_identity") or []):
        claims = claims_from_lineup(
            got.get("sides", {}), lineup_player_witnesses(got), observation_id=session,
            source_version=got.get("version", "lineup"))
        got["identity_claims"] = claims
        got["agent_identity"] = adjudicate_agent_identity(claims)
        got["agent_identity_recomputed"] = True
    from .adjudication.identity import board_side_sets, lineup_with_board
    from .adjudication.scoreboard import scoreboard_openings
    from .store import Store
    from .version import SCOREBOARD_VERDICT_COMPATIBLE, SCOREBOARD_VERSION
    board_store = Store(store)
    stored = board_store.events_version("scoreboard", session)
    if stored in SCOREBOARD_VERDICT_COMPATIBLE:
        openings = scoreboard_openings(board_store.read_events("scoreboard", session))
        got = lineup_with_board(got, board_side_sets(openings))
        got["board_state"] = {"applied": True, "version": stored,
                              "current": stored == SCOREBOARD_VERSION}
    else:
        # A stale or missing board leaves the top bar alone, and says so: a
        # version bump once dropped the board silently, and a blind label test
        # read the top bar's wrong guesses as a lineup fault. A bump that keeps
        # the verdicts joins the compatible set instead of refusing here.
        got["board_state"] = {"applied": False, "reason": _board_refusal(stored)}
    got["player"] = player_identity(got, session)
    return got


def view_stamp(session: str, store) -> str:
    """The stamp of what `load_lineup` returns now, for its consumers to
    record: `<file version>@<digest>`, the digest over the lineup file's
    bytes, the stored `self_icon` rows' bytes, the stored scoreboard stamp and
    the arbiter's version, the four things the view folds together. `no_rows`
    where no lineup file is stored. The scoreboard enters by stamp only: a
    rescan at the same stamp is invisible here, as it is to `plan`."""
    import hashlib
    import json

    from .adjudication.identity import AGENT_IDENTITY_VERSION
    from .input_stamps import NO_ROWS, file_sha16
    from .store import Store
    f = Path(store) / "lineups" / f"{session}.json"
    if not f.is_file():
        return NO_ROWS
    st = Store(store)
    parts = {"file": file_sha16(f), "self_icon": file_sha16(st.events_path("self_icon", session)),
             "scoreboard": st.events_version("scoreboard", session),
             "agent_identity": AGENT_IDENTITY_VERSION}
    try:
        version = json.loads(f.read_text(encoding="utf-8")).get("version")
    except ValueError:
        version = "unparsed"
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]
    return f"{version}@{digest}"


def _version_key(stamp: str | None) -> tuple[int, ...] | None:
    """`scoreboard-0.13.0` as (0, 13, 0); None for anything else."""
    tail = (stamp or "").rpartition("-")[2]
    parts = tail.split(".")
    return tuple(int(p) for p in parts) if parts and all(p.isdigit() for p in parts) else None


def _board_refusal(stored: str | None) -> str:
    """Why `load_lineup` leaves the top bar unconstrained by the stored board.

    A stored stamp NEWER than this code's reader is not a stale board: the
    checkout is older than the store. On 2026-09-29 a worktree at
    `scoreboard-0.12.0` read streams the player's rescan wrote at 0.13.0,
    refused every one as `stale_version`, and blamed the rescan for the top
    bar's refusals. The board is still refused, since this code cannot know
    whether the newer reader kept its verdicts, but the reason names the
    checkout.
    """
    from .version import SCOREBOARD_VERSION
    if stored is None:
        return "no_scoreboard"
    have, want = _version_key(stored), _version_key(SCOREBOARD_VERSION)
    if (stored.startswith("scoreboard-") and have is not None and want is not None
            and have > want):
        return (f"code_older_than_store {stored} > {SCOREBOARD_VERSION}: "
                "update this checkout before reading the lineup")
    return f"stale_version {stored} != {SCOREBOARD_VERSION}"


def _attach_self_icon(got: dict, session: str, store) -> bool:
    """Put the stored `self_icon` rows into a lineup whose own self-icon
    witness is empty; True when it did. Records `self_icon_state` either way."""
    from .self_icon import stored_witness
    from .store import Store
    from .version import SELF_ICON_VERSION
    witnesses = lineup_player_witnesses(got)
    if int((witnesses.get("self_icon") or {}).get("frames") or 0):
        got["self_icon_state"] = {"source": "lineup_file"}
        return False
    rows = Store(store).read_events_kind("self_icon", session, "coverage")
    stored = stored_witness(rows)
    if stored is None:
        got["self_icon_state"] = {
            "source": None, "reason": "no_self_icon_rows" if not rows else
            f"stale_version {rows[0].get('self_icon_version')} != {SELF_ICON_VERSION}"}
        return False
    got["player_witnesses"] = {**witnesses, "self_icon": stored}
    got["self_icon_state"] = {"source": "self_icon_rows", "version": SELF_ICON_VERSION}
    return True


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


def gallery_scores(hq, gal: dict[str, list[np.ndarray]]) -> dict[str, float]:
    """One composition scored against every agent's art: the histogram
    intersection summed over the agent's surfaces, as `Lineup.add` and
    `Lineup.add_self` accumulate it."""
    hq = np.asarray(hq, dtype=np.float32)
    return {n: sum(float(np.minimum(hq, g).sum()) for g in gs) for n, gs in gal.items()}


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
        got = gallery_scores(hq, self.gal)
        for j, n in enumerate(self.names):
            self.self_scores[j] += got[n]
        self.self_n += 1

    def add_tray(self, frame, store, margin_min: float = MARGIN_MIN) -> None:
        """Vote from the player's own ability tray, when it is readable."""
        if self._glyphs is None:
            self._glyphs = load_glyph_gallery(store)
        agent, _, margin = tray_vote(frame, self._glyphs)
        self.tray_frames += 1
        if agent and margin >= margin_min:
            self.tray_votes[agent] = self.tray_votes.get(agent, 0) + 1

    def player_witnesses(self) -> dict:
        """The player's witnesses as observations, for the arbiter to decide.

        The tray names the agent outright and the self icon ranks agents by
        composition; neither is combined with the other or with the top bar
        here. `identity.claims_from_lineup` turns each into a claim on the
        player entity, and `identity.player_identity` reads the verdict.
        """
        n = max(self.self_n, 1)
        return {
            "tray": {"votes": dict(sorted(self.tray_votes.items())),
                     "frames_offered": self.tray_frames},
            "self_icon": {"frames": self.self_n,
                          "scores": ({name: round(float(self.self_scores[j] / n), 5)
                                      for j, name in enumerate(self.names)}
                                     if self.self_n else {})},
        }

    def result(self, observation_id: str) -> dict:
        """The lineup record: both sides, the witnesses, their claims and the
        arbiter's verdicts, with `player` read from those verdicts."""
        sides = {side: self.verdict(side) for side in ("ally", "enemy")}
        witnesses = self.player_witnesses()
        claims = claims_from_lineup(sides, witnesses, observation_id=observation_id,
                                    source_version=LINEUP_VERSION)
        got = {"version": LINEUP_VERSION, "frames": self.frames,
               "margin_min": MARGIN_MIN, "sides": sides,
               "player_witnesses": witnesses,
               "identity_claims": claims,
               "agent_identity": adjudicate_agent_identity(claims),
               "scores": self.stored_scores()}
        got["player"] = player_identity(got, observation_id)
        return got

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
        """This side's slots, assigned by `adjudication.identity.assign_side`."""
        return assign_side(self.mean_scores(side), self.names, self.frames,
                          side, margin_min)

    def stored_scores(self) -> dict:
        """The observation to write beside the verdict, for `assign_side`.

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

    def __init__(self, profile, wh, store, name="lineup", hz=0.1, spans=None,
                 session=None):
        self.name, self.hz, self.spans = name, hz, spans
        # The claims' entity keys: the session, so a stored verdict is found
        # under the key every consumer asks for.
        self.session = session or name
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
        return [self.state.result(self.session)]


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
    got = state.result(args.session)
    rows, player = got["sides"], got["player"]
    tray = got["player_witnesses"]["tray"]
    print(f"{args.session}: {state.frames} frames sampled")
    print(f"  tray   votes {tray['votes'] or '--'} over "
          f"{tray['frames_offered']} frames offered")
    print(f"  PLAYER {player.get('agent') or '--'}"
          + (f", ally slot {player['slot']}" if player.get("slot") is not None else "")
          + f"   {player['status']} by {', '.join(player['channels']) or '--'}"
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
        out.write_text(json.dumps({**got, "session": args.session}, indent=2),
                       encoding="utf-8")
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

#: Tray cell, in source pixels. `reticle.tray` owns the slot geometry.
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
    from .tray import SLOT_DX, SLOT_KEYS, SLOT_X0
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
