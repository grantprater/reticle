"""Say what each colour-free minimap detection actually IS.

    .\\.venv\\Scripts\\python.exe prototypes\\label_dynamic.py <session> [--n 250]

Controls
--------
    1   an ABILITY icon -- any deployed utility, named later, not now
    2   an X DEATH MARK
    3   the SPIKE (dropped or planted)
    4   a PLAYER icon -- enemy, ally or self; the colour is already recorded
    5   a QUESTION MARK -- an enemy last seen here
    6   a PING -- Grant, on candidate 1 of the first real run: *sort of like a
        pond ripple, white and bluish*. Concentric expanding rings, so it is
        ANIMATED and cannot fail to light up a difference channel, and its
        fragments are thin arcs -- a second reason not to pre-filter on aspect.
        Pings are also the one thing on this widget a player PUTS there, so
        they are a different kind of fact from everything else in the list:
        they say where a teammate's attention was, not where an object is.
        Being white they read as `colour: none`, which is why they land in this
        pool at all
    8   an AREA ability -- a smoke, a wall, an ultimate's footprint. The test
        is not which ability it is, it is whether the ringed thing is a
        discrete drawn ICON or a piece of a large soft REGION. Grant, on a
        smoke: *it looks like it's pointing to the portion of the smoke in the
        doorway* -- which is what the size gate does to one. A smoke or an ult
        blows AREA_MAX (1200) and SPAN_MAX (40) outright, so what reaches this
        pool is whatever fragment a doorway happened to frame. Those two bounds
        were fitted to ICONS and nothing has ever re-derived them for areas:
        over the same 120 frames the detector throws away 265 over-size blobs
        against the 278 it keeps, median span 68 px and max 252. Keeping this
        separate from `1` matters because merging them would train a shape
        classifier on glyphs and on arbitrary doorway-shaped offcuts at once
    9   a SPAWN BARRIER -- Grant: *those represent the map borders for each side
        pre-round/buy phase*, ally green and enemy red. Added at 242/250 of the
        first run, so the first pass has them under `7`. **Now a self-check:**
        sampling is live-play only as of 2026-08-27, and a barrier is a BUY
        PHASE object, so barriers should be near-absent. If they keep appearing,
        `live_windows` is wrong -- treat a run of `9`s as a bug report about the
        sampler, not as a class
    7   something real that is none of the above -- an escape hatch, because
        `0` is a claim (this is an artefact) and being forced to make it
        wrongly is how a class gets poisoned
    0   nothing: map furniture, a viewcone edge, an artefact
    U   unsure, recorded and kept out of scoring
    A   back one
    Q / ESC  save and quit

Why this exists
---------------
`minimap_dynamic.py` finds what differs from the static map, which is the only
channel that can see the ability glyphs Grant reports are **pure black and
white** -- a red mask is blind to those by construction, so no amount of work on
`minimap_ring_fit` will ever reach them. The channel produces 1300-3900
uncoloured blobs per sweep against 200-300 red ones, and **nothing in the store
says which of those are real glyphs**. That is the blocker: the one thing the
channel is for cannot be scored at all.

It is deliberately NOT asking which ability. Detection first, identity second,
which is the order the enemy work went in and the order that let each stage be
measured on its own. "Is this an ability icon at all" needs no ability list and
no memory of what Reyna's Leer looks like from above; naming them is a second
pass over rows that already exist, exactly as `label_icon_agent.py` was a second
pass over `label_minimap.py`.

Two lessons from earlier labelling in this project are built in
---------------------------------------------------------------
* **the tile is not the object.** A 36 px crop of this widget routinely holds a
  Cypher cam AND two overlapping X marks AND a dropped spike AND ally portraits
  -- Grant, reading a contact sheet I had wrongly presented as one-object-per-
  tile. So the candidate under question is ringed in every panel, and the answer
  is about the ringed thing, not the tile;
* **never seed the file.** Seeding `minimap_agent` with provisional rows made
  the labeller skip every seeded icon as already done, and the number that came
  back was still scoring my own clustering against itself. Nothing is
  pre-filled here, and every row records who wrote it.

The blob's measured features go into the row alongside the answer -- colour,
area, box, difference magnitude -- so a classifier can be fitted later without
re-running detection, and so the eventual question "which features separate an
ability from an artefact" can be asked of the labels directly.

Sampling, rebuilt 2026-08-27 after the first pass spent itself badly
-----------------------------------------------------------------
Not pre-kill: the enemy work sampled pre-kill because that is where an enemy
provably exists, but abilities have no such anchor, and a pre-kill pool would
over-represent X marks -- a kill just happened -- and under-represent everything
placed mid-round.

The first pass then wasted itself two ways, and both are fixed here:

* **38% of its questions were about an empty minimap**, because `segment` calls
  the buy phase `active`. `live_windows` trims each round to after the spawn
  barriers drop, found per round as the last frame whose clock reads >= 95 s
  (the round timer starts at 100 s). Measured at 41 s after the round bound on
  both sessions, p10-p90 38-42 s;
* **it asked about the same object over and over.** 33 of Grant's 53 `ability`
  answers were ONE Deadlock Sonic Sensor at (137,170), and 44 of 53 were two
  positions -- 44 keypresses for two facts, because a placed device sits still
  and every sampled frame finds it again. `diversify` caps any 8 px position at
  DEDUP_CAP candidates.

Measured effect, same budget of 250 questions:

    first pass  255 answers -> 142 distinct positions   1.80 per position, worst 33
    new         250 answers -> 190 distinct positions   1.32 per position, worst 2

and on Lotus the raw stream is **51% positional repeats** before capping. Times
are also stratified ACROSS ROUNDS rather than uniform over time, so a long round
cannot buy more questions than a short one by being slow.
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_temporal import usable, drawn                        # noqa: E402
from diversity_test import descriptor, farthest_point             # noqa: E402

STORE = Path.home() / "reticle-store"

KINDS = {"1": "ability", "2": "x_mark", "3": "spike",
         "4": "player", "5": "question", "6": "ping", "7": "other",
         "8": "area", "9": "barrier", "0": "nothing"}


#: Two candidates this close in the widget are the SAME OBJECT, and asking about
#: both spends a keypress to learn nothing. On the first pass 33 of Grant's 53
#: `ability` answers were one Deadlock Sonic Sensor at (137,170) and 44 of 53
#: were two positions -- 44 keypresses for two facts.
DEDUP_PX = 8
DEDUP_CAP = 2       # at most this many questions about any one position
#: Fallback when a round's clock never reads >= 95 s. Measured at 41 s median,
#: p10-p90 38-42 s, on both a06f04a0059f and 5822b6646448.
BUY_FALLBACK_MS = 41_000


def live_windows(sid):
    """Each round trimmed to LIVE PLAY -- after the spawn barriers drop.

    `segment` calls the buy phase `active`, and the first pass drew uniformly
    over that, so **38% of the questions were about an empty minimap**. A round
    from `rounds.round_bounds` starts at the PREVIOUS scoreline increment, so it
    opens with the end-of-round animation and then the buy phase.

    The barrier drop is derivable and needs no new extractor: the round timer
    starts at 100 s, so the last frame reading >= 95 s is the drop. Measured at
    41 s after the round bound on both sessions, p10-p90 38-42 s -- but it is
    taken per round rather than assumed, and only falls back to the constant on
    the rounds whose clock never reads that high (2 of 23 on Lotus).
    """
    from reticle.rounds import round_bounds

    hp = next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet"))
    tb = pq.read_table(hp)
    ts = tb.column("t_ms").to_pylist()
    clk = tb.column("clock_ms").to_pylist()
    rounds = round_bounds(ts, tb.column("score_left").to_pylist(),
                          tb.column("score_right").to_pylist())
    if not rounds:
        raise SystemExit(f"no rounds for {sid} -- run `reticle rounds` first")
    out = []
    for r in rounds:
        a, z = r["t_start_ms"], r["t_end_ms"]
        hi = [ts[i] for i in range(len(ts))
              if a <= ts[i] < z and clk[i] is not None and clk[i] >= 95_000]
        start = max(hi) if hi else a + BUY_FALLBACK_MS
        if z - start > 5_000:
            out.append((start, z))
    return out


def live_times(sid, n, seed=17):
    """`n` sample times, spread EVENLY ACROSS ROUNDS rather than over raw time.

    Uniform-over-time hands long rounds proportionally more questions, and a
    long round is usually one slow round rather than a more interesting one.
    Stratifying per round buys variety for free.
    """
    wins = live_windows(sid)
    rng = random.Random(seed)
    out = []
    for k in range(n):
        a, b = wins[k % len(wins)]
        out.append(rng.uniform(a, b))
    return sorted(out)


#: How far back to look for the same blob when deciding whether a candidate is
#: NEW. 2 s is long enough that a placed object is certainly still there and
#: short enough that a travelling one (a deploying Omen smoke) has not left.
ONSET_LOOKBACK_MS = 2_000
ONSET_PX = 10


def split_pools(cands, rng, n_uniform):
    """Two pools, kept apart on purpose: honest rates and wide coverage.

    Sampling uniformly in TIME samples proportional to on-screen DURATION, so a
    Sonic Sensor visible for 90 s outweighs a 2 s ping ripple ~45:1. Measured on
    Lotus over 300 frames: **34 positions (12% of objects) are 60% of the raw
    pool**, and objects seen only once are 54% of the objects but 13% of the
    pool. `diversify` flattens that per POSITION; it cannot flatten it per ICON,
    because five sensors at five places are five positions showing one glyph.

    An ONSET fixes the duration bias properly: every object has exactly one
    birth however long it lives, so onset-sampling weights a ping and a sensor
    equally. It also catches the only moment some things are visible as a
    discrete icon at all -- Grant, on a deploying Omen smoke.

    **But selecting for uniqueness biases the sample**, and a biased label set
    cannot estimate a RATE. That is the trap this project already walked into
    with *0 of 55 hand-marked icons have aspect >= 2.0* -- a perfect measurement
    over the wrong population. So the pass carries two pools and says which is
    which:

        uniform     untouched selection, for precision/recall on the real
                    distribution. Small, and the only pool a rate may be quoted
                    from
        diversity   onsets first, for teaching the classifier what EXISTS.
                    Wider coverage, and a rate computed on it means nothing

    Every row records its pool, so `dynamic_eval` can never mix them by
    accident. Rows written before 2026-08-27 have no `pool` field and are read
    as `uniform`, which is what they were.
    """
    import numpy as np

    pool = list(cands)
    rng.shuffle(pool)
    uniform = pool[:n_uniform]
    rest = pool[n_uniform:]
    for c in uniform:
        c["pool"] = "uniform"
    for c in rest:
        c["pool"] = "diversity"
    # Order the diversity half by APPEARANCE novelty, greedily: each next
    # question is the candidate most unlike everything already chosen. Measured
    # against Grant's Ascent labels (`diversity_test.py`), 100 picks from 251:
    #
    #     farthest-point   rare-class rows 4.0   nothing 60    ability  9
    #     random (x200)    rare-class rows 2.7   nothing 58    ability 21
    #
    # +48% on the starved classes at no extra `nothing`, and the ability drop is
    # the point rather than a loss: random's 21 are largely one Sonic Sensor
    # seen again, these 9 are 9 different abilities. Rates come from `uniform`.
    #
    # That test selects from rows that were THEMSELVES uniformly sampled, so its
    # pool is already diversity-depleted; on a live sweep there is far more to
    # separate. Treat +48% as a floor, and re-measure once Lotus is labelled.
    keyed = [c for c in rest if c.get("vec") is not None]
    if len(keyed) > 2:
        order = farthest_point(np.stack([c["vec"] for c in keyed]), len(keyed))
        rest = [keyed[i] for i in order] + [c for c in rest if c.get("vec") is None]
    for c in pool:
        c.pop("vec", None)
    return uniform, rest


def diversify(cands, rng, cap=DEDUP_CAP, px=DEDUP_PX):
    """Cap how many candidates any one position may contribute."""
    by: dict = {}
    for c in cands:
        by.setdefault((int(c["xy"][0]) // px, int(c["xy"][1]) // px), []).append(c)
    out = []
    for v in by.values():
        rng.shuffle(v)
        out += v[:cap]
    return out, len(by)


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=250, help="candidates to present")
    ap.add_argument("--frames", type=int, default=120, help="frames to draw them from")
    ap.add_argument("--zoom", type=int, default=10)
    ap.add_argument("--diff", type=int, default=md.DIFF_MIN)
    ap.add_argument("--uniform", type=int, default=50,
                    help="questions drawn with untouched sampling, for honest "
                         "rates; the rest go to the diversity pool")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be asked, and stop")
    ap.add_argument("--colour", default=None,
                    help="only present blobs of this colour, e.g. 'none' for the "
                         "black-and-white glyphs that are the point of this")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    MX0, MY0, MX1, MY1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(args.session)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    # `static=` gives the rule Grant's painted mask produced: the opaque slab
    # plus the bomb sites, and nothing else. No guard, no fringe, no pockets --
    # see `minimap_dynamic.searchable`. Stream 925 -> 278 over the same frames,
    # with reachable hand-marked centres going UP, 212 -> 241 of 254.
    ok_area = md.searchable(labels, static=static)
    # `usable` asks whether the widget is drawn at all in this frame, which is a
    # different question from where a detection may sit -- it wants the whole
    # footprint, not the searchable part.
    floor = labels != md.VOID

    out_path = STORE / "labels" / "minimap_dynamic" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["t_ms"], r["x"], r["y"]))

    print("detecting candidates...")
    n_undrawn = 0
    cap = cv2.VideoCapture(src["path"])
    cands = []
    def detections_at(t_ms):
        """Colour-filtered detections at a time, or None if the frame is unusable."""
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        got, f = cap.read()
        if not got:
            return None
        c = f[MY0:MY1, MX0:MX1]
        if not usable(c, floor) or not drawn(c, sgray, floor):
            return None
        return [d for d in md.detect(c, sgray, ok_area, args.diff)
                if not args.colour or d["colour"] == args.colour]

    for t in live_times(args.session, args.frames):
        # One extra decode per FRAME, not per candidate: everything found at t
        # shares the same lookback.
        prev = detections_at(t - ONSET_LOOKBACK_MS)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[MY0:MY1, MX0:MX1]
        if not usable(crop, floor):
            continue
        # `usable` asks whether the widget is READABLE; `drawn` asks whether it
        # is there at all. On the death screen Valorant swaps the corner widget
        # for the full map centre-screen, and the ROI then holds world pixels
        # that pass every brightness test. Caught 4 questions into the Lotus
        # pass by Grant, who noticed a circled item outside the minimap bounds.
        if not drawn(crop, sgray, floor):
            n_undrawn += 1
            continue
        for d in md.detect(crop, sgray, ok_area, args.diff):
            if args.colour and d["colour"] != args.colour:
                continue
            key = (round(t), int(d["xy"][0]), int(d["xy"][1]))
            if key in done:
                continue
            # NEW since the lookback? `None` when the lookback frame was
            # unreadable, which is not the same as "was already there".
            onset = None
            if prev is not None:
                onset = not any(abs(q["xy"][0] - d["xy"][0]) <= ONSET_PX
                                and abs(q["xy"][1] - d["xy"][1]) <= ONSET_PX
                                for q in prev)
            cands.append({"t_ms": round(t), "onset": onset,
                          "vec": descriptor(crop, int(d["xy"][0]), int(d["xy"][1])),
                          **d})
    rng = random.Random(23)
    if n_undrawn:
        print(f"skipped {n_undrawn} frames with no minimap widget drawn "
              f"(death screen / full-map overlay)")
    raw = len(cands)
    cands, n_pos = diversify(cands, rng)
    print(f"{raw} candidates at {n_pos} distinct positions "
          f"-> {len(cands)} after capping {DEDUP_CAP} per position "
          f"({1 - len(cands) / max(1, raw):.0%} redundant)")
    n_on = sum(1 for c in cands if c.get("onset") is True)
    n_unk = sum(1 for c in cands if c.get("onset") is None)
    print(f"{n_on} are NEW since {ONSET_LOOKBACK_MS / 1000:.0f}s earlier, "
          f"{n_unk} unknown (lookback frame unreadable)")
    n_uniform = min(args.uniform, args.n, len(cands))
    uniform, diversity = split_pools(cands, rng, n_uniform)
    cands = uniform + diversity[:max(0, args.n - len(uniform))]
    print(f"asking {len(uniform)} uniform + {len(cands) - len(uniform)} diversity "
          f"(diversity ordered by appearance novelty, farthest-point)")
    # Shuffled together so the pool is invisible while answering.
    rng.shuffle(cands)
    if not cands:
        print("no candidates to label")
        return 0
    if args.dry_run:
        from collections import Counter
        rounds_hit = len({round(c["t_ms"] / 1000) // 60 for c in cands})
        print(f"DRY RUN: {len(cands)} questions, "
              f"{len({(int(c['xy'][0]) // DEDUP_PX, int(c['xy'][1]) // DEDUP_PX) for c in cands})} "
              f"distinct positions, colours "
              f"{dict(Counter(c['colour'] for c in cands))}")
        return 0
    from collections import Counter
    print(f"{len(cands)} candidates, colours: "
          f"{dict(Counter(c['colour'] for c in cands))}")

    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "img": None, "written": 0}

    root = tk.Tk()
    root.title("reticle - what is this?")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")

    def show():
        c = cands[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(c["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            step(+1, None)
            return
        crop = frame[MY0:MY1, MX0:MX1]
        cx, cy = int(c["xy"][0]), int(c["xy"][1])
        p = 20
        y0, x0 = max(0, cy - p), max(0, cx - p)
        tile = crop[y0:cy + p, x0:cx + p]
        big = cv2.resize(tile, None, fx=args.zoom, fy=args.zoom,
                         interpolation=cv2.INTER_NEAREST)
        bh, bw = big.shape[:2]
        mini = cv2.resize(crop, None, fx=bh / crop.shape[0], fy=bh / crop.shape[0],
                          interpolation=cv2.INTER_NEAREST)
        fs = bh / frame.shape[0]
        full = cv2.resize(frame, None, fx=fs, fy=fs, interpolation=cv2.INTER_AREA)
        view = np.hstack([big, mini, full[:bh]])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        # Ring the candidate in BOTH panels. The tile is not the object -- it
        # routinely holds three or four -- so the question has to point.
        tx = (cx - x0) * args.zoom
        ty = (cy - y0) * args.zoom
        canvas.create_oval(tx - 34, ty - 34, tx + 34, ty + 34, outline="#40ff40", width=3)
        sc = bh / crop.shape[0]
        canvas.create_oval(bw + cx * sc - 14, cy * sc - 14,
                           bw + cx * sc + 14, cy * sc + 14, outline="#40ff40", width=2)
        canvas.create_text(8, 8, anchor="nw", fill="#40ff40",
                           font=("Consolas", 13, "bold"), text="what is the RINGED thing?")
        s = c["t_ms"] // 1000
        canvas.create_text(bw + 8, 8, anchor="nw", fill="#a0a0a0",
                           font=("Consolas", 11), text=f"{s//60}:{s%60:02d}")
        status.config(
            text=f"  {state['i']+1}/{len(cands)}   colour={c['colour']} "
                 f"area={c['area']}   "
                 f"1=ability(glyph) 8=area(smoke/ult/wall) 2=X 3=spike "
                 f"4=player 5=question 6=ping 9=barrier 7=other 0=nothing "
                 f"U=unsure A=back Q=quit")

    def step(delta, kind):
        if kind is not None:
            c = cands[state["i"]]
            fh.write(json.dumps({
                "session_id": args.session,
                "t_ms": c["t_ms"],
                # Minimap-crop pixels at original resolution, matching
                # label_minimap's convention.
                "x": int(c["xy"][0]), "y": int(c["xy"][1]),
                "roi": [MX0, MY0, MX1, MY1],
                # The measured features, stored with the answer so a classifier
                # can be fitted later without re-running detection.
                "colour": c["colour"], "colour_frac": round(c["colour_frac"], 3),
                "area": c["area"], "box": list(c["box"]),
                "diff_min": args.diff,
                # Aspect is stored rather than filtered on. It looks decisive --
                # 0 of 55 blobs at Grant's hand-marked icons reach 2.0, p95 1.71,
                # against 25% of the candidate stream at 2.5+ -- but those 55 are
                # ENEMY icons, and a Sage or Viper wall is drawn on the minimap as
                # a long thin shape. Filtering the pool on it before the labels
                # exist would delete exactly the abilities this pass is for.
                "aspect": round(max(c["box"][2], c["box"][3])
                                / max(1, min(c["box"][2], c["box"][3])), 2),
                # Which pool this question came from, and whether the blob
                # was new. A rate may only be quoted from `uniform`.
                "pool": c.get("pool", "uniform"),
                "onset": c.get("onset"),
                "kind": None if kind == "__unsure__" else kind,
                "uncertain": kind == "__unsure__",
                "by": "grant",
            }) + chr(10))
            fh.flush()
            state["written"] += 1
        state["i"] += delta
        if not (0 <= state["i"] < len(cands)):
            finish()
            return
        show()

    def finish():
        fh.close()
        cap.release()
        print(f"wrote {state['written']} labels to {out_path}")
        root.destroy()

    for key, name in KINDS.items():
        root.bind(key, lambda e, n=name: step(+1, n))
    root.bind("u", lambda e: step(+1, "__unsure__"))
    root.bind("a", lambda e: step(-1, None))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)

    show()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
