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
`7010b3d62460`, 90 frames spaced across the session, official art only, no
session mining and no labels:

    slot   answer     margin over the runner-up    truth
    1      Sage         0.132                      correct
    2      Phoenix      0.109                      correct
    4      Cypher       0.109                      correct
    0      Sova         0.035                      WRONG (truth Chamber,
                                                    which is the runner-up)
    3      Raze         0.031                      WRONG (truth Brimstone)

The margin separates them completely, so the gate is the margin and a slot
below it stays `None` with a reason rather than guessing. `MARGIN_MIN` is a
PROVISIONAL cut resting on one lineup of five slots -- every verdict carries
its margin so a real cut can be fitted when more lineups are known.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import cv2
import numpy as np

from .roster import ART_FRAC, N_SLOTS, roster_rois
from .track import assign

LINEUP_VERSION = "lineup-0.1.0"

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

    def add(self, frame: np.ndarray, profile, w: int, h: int) -> bool:
        rois = dict(zip(("ally", "enemy"), roster_rois(profile, w, h)))
        seen = False
        for side, roi in rois.items():
            if roi is None:
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

    def verdict(self, side: str, margin_min: float = MARGIN_MIN) -> list[dict]:
        """One row per slot: the agent, its margin, and whether to believe it.

        The five slots are five DIFFERENT agents, so this is an assignment and
        not five arg-maxes -- the same constraint the tracker uses on icons,
        for the same reason. A slot under the margin is `None` WITH its best
        guess kept beside it, because an unread value must say what it is.
        """
        s = self.scores[side] / max(self.frames, 1)
        picked = assign([[-float(v) for v in row] for row in s])
        out = []
        for i, j in enumerate(picked):
            order = np.argsort(-s[i])
            best, runner = float(s[i, order[0]]), float(s[i, order[1]])
            margin = best - runner
            ok = j >= 0 and margin >= margin_min
            out.append({
                "slot": i, "side": side,
                "agent": self.names[j] if ok else None,
                "best_guess": self.names[order[0]],
                "score": round(float(s[i, j]) if j >= 0 else 0.0, 4),
                "margin": round(margin, 4),
                "frames": self.frames,
                "reason": None if ok else
                          f"margin {margin:.3f} below {margin_min} -- "
                          f"not separated from {self.names[order[1]]}",
            })
        return out


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
        self.state = Lineup(load_gallery(store))

    def feed(self, smp) -> None:
        self.state.add(smp.frame, self.profile, self.w, self.h)

    def finish(self):
        return [{"version": LINEUP_VERSION, "frames": self.state.frames,
                 "margin_min": MARGIN_MIN,
                 "sides": {side: self.state.verdict(side)
                           for side in ("ally", "enemy")}}]


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
    print(f"{args.session}: {state.frames} frames sampled")
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
                                   "sides": rows}, indent=2), encoding="utf-8")
        print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


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
