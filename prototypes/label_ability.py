"""Say WHICH ability each already-marked minimap glyph is.

    .\\.venv\\Scripts\\python.exe prototypes\\label_ability.py <session>

Controls
--------
    1-9    pick a category from the legend shown on screen -- it lists the
           most recently used categories, so the ones you need are usually
           right there
    N      new / any category by name -- opens a small box for AGENT and
           ABILITY. Typing an agent+ability that already exists reuses it
           rather than making a duplicate, so this is also how you reach a
           category that has scrolled out of the 1-9 legend
    0      not actually an ability -- the previous pass got this one wrong
    U      unsure -- recorded, and kept out of scoring
    A      back one
    Q / ESC  save and quit

Why this exists
----------------
`label_dynamic.py` asks "is this an ability glyph at all", deliberately not
which one -- detection first, identity second, the same order
`label_icon_agent.py` used for enemy portraits. That order let both stages be
measured on their own, and it is why this is a SECOND pass over rows that
already exist rather than a new sampling: every row here is a `kind: ability`
answer already sitting in `<store>/labels/minimap_dynamic/<session>.jsonl`.

It is worth doing now rather than later because of what the first pass's own
numbers say. On `a06f04a0059f`, 33 of 53 `ability` answers are one Deadlock
Sonic Sensor at (137,170) and 44 of 53 are two positions -- a placed device
sits still, so every sampled frame finds it again. Any recall/precision number
fitted on the class as it stands is mostly measuring "can we find this one
sensor twice", not "can we find an ability glyph". Splitting the class by
identity is what makes that visible, and it is also the thing CLAUDE.md's
"How team gets attributed" section depends on: ability -> agent is nearly 1:1,
so naming the glyph gets its team for free from the scoreboard lineup.

Design, from what Grant asked for on 2026-08-27
-------------------------------------------------
The category list is long and not known in advance -- new abilities keep
turning up unannounced, the same way `barrier` and `area` surfaced mid-run in
the first pass and cost a restart each time. So there is no fixed keymap here.
Categories are created on the fly (`N`), and the 1-9 legend always shows
whichever ones were used most recently -- the ones a run of similar candidates
actually needs, since a placed device tends to reappear in bursts. Typing a
name that already exists (case-insensitive, same agent+ability) reuses the
category rather than forking it, so `N` also doubles as "jump to a category
that isn't in the visible nine".

Every category carries an EXPLICIT agent, separate from the ability name, per
Grant: identity is per-ability, "with an inheritance relationship to their
agent". `agent=""` is allowed and means "not attributable to one agent" -- the
one deliberate case is below.

**All deployed smokes are one category, `(agent="", ability="smoke_deployed")`,
seeded in on first run.** Grant's call: several agents smoke (Brimstone, Omen,
Astra, Viper's wall reads differently and is NOT this), and once a smoke has
landed it is a generic soft grey patch on the minimap with no readable
per-agent detail -- there is nothing left in the pixels to split on, so forcing
a split would be inventing precision the glyph does not carry. Every other
category is per-ability by design.

The category registry (`<store>/labels/ability_categories.json`) is GLOBAL,
not per-session -- unlike the answer rows. An ability's minimap art is the same
asset in every match, the same reasoning `confounders.npz` already relies on
for X marks and question marks, so a category named while labelling one
session should be offered again in the next one rather than retyped.

Two lessons already paid for elsewhere are reused rather than re-learned:
* **never seed the answer file** -- pre-filling rows as done breaks resumption
  (`label_icon_agent.py`'s docstring). This seeds the CATEGORY vocabulary, not
  an answer to any row, which is a different thing: it costs Grant nothing to
  have "smoke_deployed" already on the list and it does not mark any candidate
  as labelled.
* **the tile is not the object** -- the candidate is ringed in both the zoomed
  tile and the wide minimap panel, exactly as `label_dynamic.py` does, because
  the same crop that showed a Cypher cam beside two X marks and a dropped spike
  applies here too.

A second candidate source, for controlled clips (2026-08-27)
----------------------------------------------------------------
`scan_ability_clip.py` proposes candidates directly, for a short deliberate
clip rather than a full match -- see its docstring. Those rows are a machine
GUESS (`by: "claude"`) at `<store>/labels/ability_candidates/<session>.jsonl`,
not a verified `kind: ability` answer, so this pass does double duty on them:
`0 = not actually an ability` corrects the detection, and everything else
still names the identity. Preferred automatically when that file exists;
`--source` overrides.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from dynamic_eval import load as load_dynamic_labels, COLLAPSE_PX   # noqa: E402

STORE = Path.home() / "reticle-store"
CATS_PATH = STORE / "labels" / "ability_categories.json"


def collapse_positions(rows, px=COLLAPSE_PX):
    """One candidate per physical object, not per observation.

    `label_dynamic.py`'s own diversify/uniform-vs-diversity split (2026-08-27)
    keeps `label_dynamic` from over-asking about one static object -- but it
    only governs what gets asked about VIDEO DETECTIONS, and rows tagged
    `ability` before that fix still carry the old duplication: 33 of
    `a06f04a0059f`'s 53 are one Deadlock Sonic Sensor at (137,170).

    Collapsing again here is correct for an IDENTITY question in a way it
    would not be for a RATE question -- `dynamic_eval.report()` keeps both
    per-row and `--by-position` numbers apart for exactly that reason, because
    collapsing before scoring a rate hides how often the class actually fires.
    Naming a glyph is not a rate: asking about the same sensor thirty-three
    times teaches nothing that asking once does not, so every row this drops
    costs nothing. `n_observations` keeps the count instead of throwing it
    away, so a later pass can still tell "labelled once, backs 33 sightings"
    from "labelled once, backs one".
    """
    groups: dict = {}
    for r in rows:
        groups.setdefault((int(r["x"]) // px, int(r["y"]) // px), []).append(r)
    out = []
    for g in groups.values():
        g.sort(key=lambda r: r["t_ms"])
        rep = dict(g[0])
        rep["n_observations"] = len(g)
        out.append(rep)
    return out


def load_scan_candidates(sid):
    """Machine-proposed candidates from `scan_ability_clip.py`, if any.

    Already one row per TRACK (see that module), so not collapsed again here
    -- two tracks at the same pixel are two separate placements in time, worth
    asking about individually, unlike `collapse_positions`'s raw per-frame
    duplicates from the match-sampling path.
    """
    p = STORE / "labels" / "ability_candidates" / f"{sid}.jsonl"
    if not p.is_file():
        return []
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return list({(r["t_ms"], r["x"], r["y"]): r for r in rows}.values())


#: Seeded once, never as an answer -- see "All deployed smokes" above.
SEED_CATEGORIES = [{"agent": "", "ability": "smoke_deployed"}]

#: How many recently-used categories the 1-9 legend shows.
LEGEND_N = 9


def cat_id(agent: str, ability: str) -> str:
    agent, ability = agent.strip().lower(), ability.strip().lower()
    return f"{agent}:{ability}" if agent else ability


def load_categories():
    """The global category registry, seeded on first use.

    `seq` is a use counter, bumped every time a category is created or picked,
    so sorting by it descending gives the MRU legend without storing wall-clock
    time or depending on file order.
    """
    if CATS_PATH.is_file():
        return json.loads(CATS_PATH.read_text(encoding="utf-8"))
    CATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    reg = {"next_seq": 0, "categories": {}}
    for c in SEED_CATEGORIES:
        cid = cat_id(c["agent"], c["ability"])
        reg["categories"][cid] = {"agent": c["agent"], "ability": c["ability"],
                                  "seq": reg["next_seq"]}
        reg["next_seq"] += 1
    save_categories(reg)
    return reg


def save_categories(reg):
    CATS_PATH.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def touch_category(reg, agent: str, ability: str) -> str:
    """Create-or-reuse a category and bump it to the front of the MRU order."""
    cid = cat_id(agent, ability)
    reg["categories"].setdefault(cid, {"agent": agent.strip(), "ability": ability.strip()})
    reg["categories"][cid]["seq"] = reg["next_seq"]
    reg["next_seq"] += 1
    save_categories(reg)
    return cid


def mru(reg, n=LEGEND_N):
    return sorted(reg["categories"].items(), key=lambda kv: -kv[1]["seq"])[:n]


def main() -> int:
    import tkinter as tk
    from tkinter import simpledialog

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--zoom", type=int, default=10)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--source", choices=("auto", "dynamic", "candidates"), default="auto",
                    help="'candidates' = scan_ability_clip.py's machine guesses (unverified, "
                         "0 corrects a bad detection too); 'dynamic' = previously human-"
                         "classified kind=ability rows from label_dynamic.py; 'auto' prefers "
                         "candidates when that file exists")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])

    cand_path = STORE / "labels" / "ability_candidates" / f"{args.session}.jsonl"
    from_candidates = args.source == "candidates" or (args.source == "auto" and cand_path.is_file())
    if from_candidates:
        rows = load_scan_candidates(args.session)
        if not rows:
            print(f"no scanned candidates for {args.session} -- run scan_ability_clip.py first")
            return 0
        print(f"{len(rows)} scanned candidates from scan_ability_clip.py (unverified -- "
              f"0 means the detection itself was wrong, not just the name)")
    else:
        # The rows under test: `kind: ability` from the first pass. Loaded through
        # `dynamic_eval.load` rather than re-parsed here -- same last-write-wins
        # convention, one place that defines it.
        rows = [r for r in load_dynamic_labels(args.session) if r["kind"] == "ability"]
        if not rows:
            print(f"no 'ability' rows for {args.session} -- run label_dynamic.py first")
            return 0
        rows = collapse_positions(rows)

    out_path = STORE / "labels" / "ability" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("by", "grant") == "grant":
                    done.add((r["t_ms"], r["x"], r["y"]))

    items = [r for r in rows if args.redo or (r["t_ms"], r["x"], r["y"]) not in done]
    if not items:
        print("every 'ability' position in this session already has an identity")
        return 0
    obs = sum(r["n_observations"] for r in rows)
    print(f"{len(rows)} distinct candidates (backed by {obs} raw observations total), "
          f"{len(done)} already done, {len(items)} to go")

    reg = load_categories()
    cap = cv2.VideoCapture(src["path"])
    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "img": None, "written": 0}

    root = tk.Tk()
    root.title("reticle - which ability is this?" +
              (" (unverified auto-detection -- 0 if it's wrong)" if from_candidates else ""))
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11), justify="left")
    status.pack(fill="x")

    def show():
        r = items[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            step(+1, None)
            return
        mx0, my0, mx1, my1 = r["roi"]
        crop = frame[my0:my1, mx0:mx1]
        cx, cy = int(r["x"]), int(r["y"])
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
        # Ring the candidate in both panels -- the tile is not the object.
        tx, ty = (cx - x0) * args.zoom, (cy - y0) * args.zoom
        canvas.create_oval(tx - 34, ty - 34, tx + 34, ty + 34, outline="#40ff40", width=3)
        sc = bh / crop.shape[0]
        canvas.create_oval(bw + cx * sc - 14, cy * sc - 14,
                           bw + cx * sc + 14, cy * sc + 14, outline="#40ff40", width=2)
        canvas.create_text(8, 8, anchor="nw", fill="#40ff40",
                           font=("Consolas", 13, "bold"), text="which ability is the RINGED thing?")
        s = r["t_ms"] // 1000
        canvas.create_text(bw + 8, 8, anchor="nw", fill="#a0a0a0",
                           font=("Consolas", 11), text=f"{s//60}:{s%60:02d}")
        legend = "  ".join(f"{i+1}={a['agent'] + ':' if a['agent'] else ''}{a['ability']}"
                           for i, (_, a) in enumerate(mru(reg)))
        status.config(
            text=f"  {state['i']+1}/{len(items)}   area={r['area']} colour={r['colour']} "
                 f"seen {r['n_observations']}x in the raw pass\n"
                 f"  {legend}\n"
                 f"  N=new/pick-by-name   0=not-actually-ability   U=unsure   A=back   Q=quit")

    def record(cid, agent, ability, uncertain, not_ability=False):
        r = items[state["i"]]
        fh.write(json.dumps({
            "session_id": args.session,
            "t_ms": r["t_ms"], "x": r["x"], "y": r["y"], "roi": r["roi"],
            "source_kind": r["kind"], "n_observations": r["n_observations"],
            "category_id": None if (uncertain or not_ability) else cid,
            "agent": None if (uncertain or not_ability) else agent,
            "ability": None if (uncertain or not_ability) else ability,
            "not_ability": not_ability,
            "uncertain": uncertain,
            "by": "grant",
        }) + chr(10))
        fh.flush()
        state["written"] += 1

    def step(delta, action):
        # `action` is one of: None (no record, e.g. a bad frame read),
        # ("cat", cid, agent, ability), "unsure", or "not_ability".
        if action == "unsure":
            record(None, None, None, True)
        elif action == "not_ability":
            record(None, None, None, False, not_ability=True)
        elif isinstance(action, tuple):
            _, cid, agent, ability = action
            record(cid, agent, ability, False)
        state["i"] += delta
        if not (0 <= state["i"] < len(items)):
            finish()
            return
        show()

    def pick(idx):
        m = mru(reg)
        if idx >= len(m):
            return
        cid, a = m[idx]
        touch_category(reg, a["agent"], a["ability"])
        step(+1, ("cat", cid, a["agent"], a["ability"]))

    def new_category():
        agent = simpledialog.askstring("agent", "agent (blank if none):", parent=root) or ""
        ability = simpledialog.askstring("ability", "ability name:", parent=root)
        if not ability:
            show()   # cancelled -- redraw, since the dialog steals focus
            return
        cid = touch_category(reg, agent, ability)
        step(+1, ("cat", cid, agent.strip().lower(), ability.strip().lower()))

    def finish():
        fh.close()
        cap.release()
        print(f"wrote {state['written']} ability labels to {out_path}")
        root.destroy()

    for k in range(1, LEGEND_N + 1):
        root.bind(str(k), lambda e, i=k - 1: pick(i))
    root.bind("0", lambda e: step(+1, "not_ability"))
    root.bind("n", lambda e: new_category())
    root.bind("u", lambda e: step(+1, "unsure"))
    root.bind("a", lambda e: step(-1, None))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)

    show()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
