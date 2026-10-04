r"""Ask the player what the minimap glyph evaluation cannot derive.

    .\.venv\Scripts\python.exe prototypes\ask_minimap_glyphs.py            [--kinds texture,visibility,rotation] [--by player] [--reask-unsure]
    .\.venv\Scripts\python.exe prototypes\ask_minimap_glyphs.py --list     (print the questions; write nothing)

Three kinds of question, in this order:

* texture: which ability draws this exported minimap texture? One screen per
  texture stem (its state variants side by side), beside the agent's four
  DisplayIcons. Asked for every inventory row (`minimap_glyph_eval.py
  inventory`) whose mapping the player's labelled crops did not prove, the
  icon-correlation proposals included: the game's file letters disagree with
  the catalogue's keys (Deadlock's E texture fits the labelled Barrier Mesh,
  the catalogue's C), so a letter proves nothing. Not asked:
  a stem a domain fact answers (`Minimap_Smokes`
  [domain:abilities/smoke-attribution]; `Sarge_Gauntlet_minimap`
  [domain:abilities/brimstone-gauntlet-texture-belief]), and a stem whose
  only evidence of being a HUD marker is its name (no row correlates with a
  labelled crop or a DisplayIcon); `--list` prints those to glance at.
* visibility: what does the ability draw on one view's minimap, an icon, a
  shape, both or nothing? Each ability decides on its own what the caster, a
  teammate and an enemy see [domain:abilities/views-separate-per-ability], so
  each view is its own question (`visibility:<agent>:<slot>:self|ally|enemy`;
  `ally` is the teammate's view, the key the player's earlier answers used)
  and no view's answer settles another's. A view is settled only by the
  player's own answer to that view's key, or, for `self` alone, by a sheet
  Minimap cell (the caster's view) that carries a domain fact and no `?`,
  census vote or split. The spectator view is not asked: the player believes
  it is the self view less the audio circle
  [domain:minimap/spectator-view-matches-self]. The `drawing` answers given
  under the retired prompt, which said all views draw alike, settle no view.
  Order: abilities with a proposed texture, then those the game data
  (`ability-states-gamedata-0.2.0`) gives a minimap drawing, then the rest;
  per ability self, teammate, enemy. The game data's views are printed
  beside a question as an annotation, never as its answer.
* rotation: does the ability's icon turn with its placement, or stay
  upright? Asked for each labelled ability, showing up to eight of its crops
  the evaluation named right, each with the rotation the fit chose.

Controls (labelling-pass): digit keys pick an answer; 7 = other (type it);
U = unsure (kept out of scoring); A = back one; Q or ESC = save and quit.
Every answer appends one row to
`<store>/labels/minimap_glyph_questions/answers.jsonl`, flushed at once; the
last row for a key wins, and a rerun skips answered keys (an unsure answer
too, unless `--reask-unsure`). Nothing is seeded:
the proposals the evaluation made are shown as text for comparison and are
never preselected.

Wire: no. It asks; `minimap_glyph_eval.py` and the mechanics sheet consume
the answers once the player gives them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import minimap_glyph_eval as ev  # noqa: E402

VERSION = "ask-minimap-glyphs-0.2.0"
ANSWERS = ev.STORE / "labels" / "minimap_glyph_questions" / "answers.jsonl"
SHEET = Path(__file__).resolve().parents[1] / "docs" / "ABILITY_MECHANICS_SHEET.md"
GAMEDATA = ev.STORE / "reference" / "ability-states" / "ability-states-gamedata-0.2.0.jsonl"
SLOTS = "CQEX"
#: The asked views: answer-file key suffix -> the game data's view name and the words the prompt uses.
VIEWS = {"self": ("self", "your own (the caster's)"), "ally": ("teammate", "a teammate's"),
         "enemy": ("enemy", "an enemy's, inside vision")}
VIEW_OPTS = {"1": "icon", "2": "shape (disc, area, line, wedge)", "3": "icon and shape", "4": "nothing",
             "7": "other (type it)"}
ROT_OPTS = {"1": "turns to any angle with its placement", "2": "always upright",
            "3": "a few fixed orientations (type which under 7 if unsure)", "7": "other (type it)"}


# ------------------------------------------------------------------ questions

def sheet_minimap() -> dict:
    """(agent, slot) -> (ability, the sheet's Minimap cell) for every C/Q/E/X row of the mechanics sheet. Each
    agent table's header row names its columns; the Ability and Minimap cells are found by header name, so a
    column added to the sheet moves no answer."""
    out, agent, col = {}, None, None
    for line in SHEET.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            agent, col = m.group(1).strip(), None
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Slot":
            col = {name: i for i, name in enumerate(cells)}
            if "Minimap" not in col or "Ability" not in col:
                raise SystemExit(f"mechanics sheet table for {agent} lacks an Ability or Minimap column")
            continue
        if agent and col and cells[0] in SLOTS and len(cells[0]) == 1 and len(cells) > col["Minimap"]:
            out[(agent, cells[0])] = (cells[col["Ability"]], cells[col["Minimap"]])
    return out


def undecided(cell: str) -> str | None:
    """Why the sheet's Minimap cell leaves the question open, or None when a fact decides the caster's view."""
    if cell.strip() in ("", "?"):
        return "no answer"
    if "split" in cell:
        return "split census vote"
    if "census 1" in cell:
        return "single census vote"
    if "?" in cell:
        return "an open question"
    if "[domain:" not in cell:
        return "no domain fact"
    return None


#: Texture stems a domain fact already answers; never asked.
TEXTURE_FACTS = {
    "Minimap_Smokes": "abilities/smoke-attribution",       # one smoke marker; a smoke names no agent by its drawing
    "Sarge_Gauntlet_minimap": "abilities/brimstone-gauntlet-texture-belief",   # the tablet's map, not the HUD's
}
#: Evidence that a texture is a HUD minimap marker beyond its name: a median best Pearson with the player's
#: labelled crops of one ability at least LABEL_EVIDENCE, or a DisplayIcon correlation at least ICON_EVIDENCE
#: (the inventory's own proposal thresholds, gaps ignored).
LABEL_EVIDENCE, ICON_EVIDENCE = 0.6, 0.5
#: Visibility facts: each ability decides each view on its own [domain:abilities/views-separate-per-ability], so
#: no view's answer settles another's; the spectator view is believed to be the self view less the audio circle
#: [domain:minimap/spectator-view-matches-self] and is not asked.
VIEW_FACTS = ("abilities/views-separate-per-ability", "minimap/spectator-view-matches-self")


def check_facts() -> None:
    """Every fact the pruning cites must exist; a renamed fact fails loudly."""
    from reticle import domain
    facts = domain.load()
    cited = list(TEXTURE_FACTS.values()) + list(VIEW_FACTS)
    missing = [k for k in cited if k not in facts]
    if missing:
        raise SystemExit(f"domain facts missing: {missing}")


def name_only(rows: list[dict]) -> bool:
    """True when no row of a stem correlates with a labelled crop or a DisplayIcon: only its name says minimap."""
    def top(v):
        return v[0][0] if v else -1.0
    return all(top(r.get("label_corr")) < LABEL_EVIDENCE and top(r.get("icon_corr")) < ICON_EVIDENCE for r in rows)


def texture_groups(inv: dict) -> dict:
    groups = defaultdict(list)
    for r in inv["rows"]:
        if r["kind"] != "candidate" or r.get("status") == "labels":
            continue
        stem = re.sub(r"_(" + "|".join(ev.STATE_WORDS) + r")$", "", r["name"], flags=re.I)
        groups[stem].append(r)
    return groups


def texture_pruned(inv: dict) -> tuple[list, list]:
    """(stems a domain fact answers, with the fact), (stems whose only marker evidence is the name, with values)."""
    by_fact, glance = [], []
    for stem, rows in sorted(texture_groups(inv).items()):
        if stem in TEXTURE_FACTS:
            by_fact.append((stem, TEXTURE_FACTS[stem]))
        elif name_only(rows):
            glance.append((stem, rows[0]["agent"], max((r["icon_corr"][0][0] for r in rows if r.get("icon_corr")),
                                                        default=None),
                           max((r["label_corr"][0][0] for r in rows if r.get("label_corr")), default=None)))
    return by_fact, glance


def texture_questions(inv: dict) -> list[dict]:
    by_fact, glance = texture_pruned(inv)
    drop = {s for s, _ in by_fact} | {g[0] for g in glance}
    qs = []
    for stem, rows in sorted(texture_groups(inv).items()):
        if stem in drop:
            continue
        rows.sort(key=lambda r: r["name"])
        qs.append({"kind": "texture", "key": f"texture:{stem}", "stem": stem, "agent": rows[0]["agent"],
                   "files": [r["file"] for r in rows],
                   "shown": {"proposed": sorted({r.get("proposed") or "-" for r in rows}),
                             "status": sorted({r["status"] for r in rows}),
                             "icon_corr": rows[0]["icon_corr"][:2], "label_corr": rows[0]["label_corr"][:2]}})
    return qs


def gamedata_views(path: Path = GAMEDATA) -> dict:
    """{(agent, slot): {"views": {view: {"drawn": n, "not_drawn": n, "unknown": n}}, "cues": [texture stems]}}
    over the game data's minimap rows (a `minimap_*` cue, or a texture cue under a Minimap folder). An annotation
    and an ordering key only: a question shows it, never takes it as the answer."""
    out: dict = {}
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        ct, cue = r.get("cue_type") or "", str(r.get("cue") or "")
        if not (ct.startswith("minimap_") or (ct == "texture" and "/minimap" in cue.lower())):
            continue
        a = out.setdefault((r["agent"], r["key"]), {"views": {v: {"drawn": 0, "not_drawn": 0, "unknown": 0}
                                                              for v, _ in VIEWS.values()}, "cues": []})
        for v, _ in VIEWS.values():
            val = (r.get("views") or {}).get(v)
            a["views"][v]["drawn" if val is True else "not_drawn" if val is False else "unknown"] += 1
        stem = cue.rsplit("/", 1)[-1].split(".")[0]
        if stem and stem not in a["cues"]:
            a["cues"].append(stem)
    return out


def gamedata_note(gd: dict | None, agent: str, slot: str, view: str | None = None) -> str:
    """The game data's minimap views for one ability (one view, or all three), as text."""
    a = (gd or {}).get((agent, slot))
    if not a:
        return "no minimap row"
    names = [VIEWS[view][0]] if view else [v for v, _ in VIEWS.values()]
    parts = [f"{v}: {a['views'][v]['drawn']} drawn / {a['views'][v]['not_drawn']} not / "
             f"{a['views'][v]['unknown']} unknown" for v in names]
    return "; ".join(parts) + f" (cues {', '.join(a['cues'][:4]) or 'none'})"


def visibility_questions(inv: dict, pruned: list | None = None, gd: dict | None = None) -> list[dict]:
    """One question per ability and view (self, teammate as `ally`, enemy) that nothing settles. Views are separate
    per ability [domain:abilities/views-separate-per-ability]: no view's answer settles another's. The sheet's
    Minimap cell is the caster's view, so a decided cell settles `self` alone (listed in `pruned`); a player's
    answer to a view's key settles that view through the ask loop's answered keys. The game data (`gd`) orders
    the abilities and annotates the prompt; it answers nothing."""
    sheet = sheet_minimap()
    proposed = defaultdict(list)
    for r in inv["rows"]:
        if r.get("proposed"):
            proposed[r["proposed"]].append(r["name"])
    gd = gd or {}
    qs = []
    for (agent, slot), (ability, cell) in sorted(sheet.items()):
        key = f"{agent}:{slot}"
        drawn = any(c["drawn"] for c in gd.get((agent, slot), {}).get("views", {}).values())
        rank = 0 if key in proposed else 1 if drawn else 2 if (agent, slot) in gd else 3
        for i, view in enumerate(VIEWS):
            if view == "self":
                why = undecided(cell)
                if why is None:
                    if pruned is not None:
                        pruned.append((key, ability))
                    continue
                why = f"the sheet's caster-view cell: {why}"
            else:
                why = f"no answer for {VIEWS[view][1].split(',')[0]} view"
            qs.append({"kind": "visibility", "key": f"visibility:{key}:{view}", "agent": agent, "slot": slot,
                       "ability": ability, "view": view, "rank": rank, "order": i,
                       "shown": {"sheet_cell": cell if view == "self" else None, "why_asked": why,
                                 "textures": proposed.get(key, []),
                                 "game_data": gamedata_note(gd, agent, slot, view)}})
    return sorted(qs, key=lambda q: (q["rank"], q["agent"], q["slot"], q["order"]))


def rotation_questions(d: dict) -> list[dict]:
    per = defaultdict(list)
    for r in ev.positives(d["items"]):
        if r.get("rot_pred") == r["truth"]:
            per[r["truth"]].append(r)
    qs = []
    for key, rs in sorted(per.items()):
        rots = sorted({int(r["rot_fits"][key][1]) for r in rs})
        pick = sorted(rs, key=lambda r: -r["rot_margin"])[:8]
        qs.append({"kind": "rotation", "key": f"rotation:{key}", "truth": key, "ability": ev.GLYPHS[tuple(key.split(":"))]["name"],
                   "items": [(r["sid"], r["t_ms"], r["x"], r["y"], r["win_index"], int(r["rot_fits"][key][1]))
                             for r in pick],
                   "shown": {"n_right": len(rs), "fit_rotations": rots}})
    return qs


# ------------------------------------------------------------------ panels (display only: nearest-neighbour enlarging)

def _over_grey(path: str, n: int = 112) -> np.ndarray:
    im = cv2.imread(str(ev.GX / path) if not os.path.isabs(path) else path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    if im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    a = im[..., 3:4].astype(np.float32) / 255
    comp = (im[..., :3] * a + 90.0 * (1 - a)).astype(np.uint8)
    s = n / max(comp.shape[:2])
    comp = cv2.resize(comp, (max(1, int(comp.shape[1] * s)), max(1, int(comp.shape[0] * s))),
                      interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    t = np.full((n, n, 3), 90, np.uint8)
    t[:comp.shape[0], :comp.shape[1]] = comp
    return t


def _caption(img: np.ndarray, txt: str, col=(255, 255, 255)) -> np.ndarray:
    bar = np.full((16, img.shape[1], 3), 20, np.uint8)
    cv2.putText(bar, txt[: max(4, img.shape[1] // 6)], (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.36, col, 1, cv2.LINE_AA)
    return np.vstack([img, bar])


def _hcat(cells: list[np.ndarray], gap: int = 6) -> np.ndarray:
    H = max(c.shape[0] for c in cells)
    out = []
    for c in cells:
        out += [np.pad(c, ((0, H - c.shape[0]), (0, 0), (0, 0))), np.zeros((H, gap, 3), np.uint8)]
    return np.hstack(out)


def _stack(rows: list[np.ndarray]) -> np.ndarray:
    W = max(r.shape[1] for r in rows)
    return np.vstack([np.pad(r, ((0, 8), (0, W - r.shape[1]), (0, 0))) for r in rows])


def kit_row(agent: str | None) -> list[np.ndarray]:
    present = [s for s in SLOTS if agent and (agent, s) in ev.GLYPHS]
    return [_caption(_over_grey(ev.GLYPHS[(agent, s)]["file"], 96), f"{i + 1} = {s} {ev.GLYPHS[(agent, s)]['name']}")
            for i, s in enumerate(present)]


def panel(q: dict, z) -> np.ndarray:
    if q["kind"] == "texture":
        tex = [_caption(_over_grey(f), os.path.basename(f)[:-4].split("_")[-1]) for f in q["files"]]
        rows = [_hcat(tex)]
        k = kit_row(q["agent"])
        if k:
            rows.append(_hcat(k))
        return _stack(rows)
    if q["kind"] == "visibility":
        g = ev.GLYPHS.get((q["agent"], q["slot"]))
        cells = [_caption(_over_grey(g["file"], 96), "DisplayIcon")] if g else []
        by_name = {os.path.basename(f)[:-4]: f for f in ev.inv_files()}
        for name in q["shown"]["textures"][:6]:
            if name in by_name:
                cells.append(_caption(_over_grey(by_name[name], 96), name.split("_")[-1]))
        return _hcat(cells) if cells else np.zeros((60, 200, 3), np.uint8)
    # rotation: each right crop at x5, the asked-about icon ringed, the fitted rotation captioned
    cells = []
    for sid, t_ms, x, y, wi, rot in q["items"]:
        C = z["C"][wi]
        k = 5
        big = cv2.resize(C, (C.shape[1] * k, C.shape[0] * k), interpolation=cv2.INTER_NEAREST)
        c = ev.WIN * k + k // 2
        cv2.circle(big, (c, c), int(13 * k), (0, 255, 0), 1)
        cells.append(_caption(big, f"{sid[:6]} {t_ms / 1000:.1f}s fit {rot} deg"))
    rows = [_hcat(cells[:4])] + ([_hcat(cells[4:])] if len(cells) > 4 else [])
    return _stack(rows)


def prompt(q: dict) -> str:
    sh = q["shown"]
    if q["kind"] == "texture":
        return (f"TEXTURE {q['stem']}  (agent from the file's code name: {q['agent']})\n"
                f"Which ability draws this marker on the minimap?\n"
                f"1-4 = the kit ability shown below; 5 = this agent, but not one of its four (a passive, pickup, "
                f"or state); 6 = not an ability marker; 7 = other (type it); U = unsure.\n"
                f"Evaluation's proposal, for comparison only: {sh['proposed']} {sh['status']}; "
                f"icon correlation {sh['icon_corr']}; label correlation {sh['label_corr']}")
    if q["kind"] == "visibility":
        opts = "; ".join(f"{k} = {v}" for k, v in VIEW_OPTS.items())
        cell = f" The sheet's caster-view cell: {sh['sheet_cell'][:220]}" if sh.get("sheet_cell") else ""
        return (f"{q['agent']} {q['slot']} {q['ability']}, {VIEWS[q['view']][1].upper()} VIEW: what does it draw on "
                f"{VIEWS[q['view']][1]} minimap while it is out? (Views are separate per ability; answer this "
                f"view alone.)\n{opts}; U = unsure.\nAsked because: {sh['why_asked']}.{cell}\n"
                f"Game data for this view (an annotation, not an answer): {sh['game_data']}\n"
                f"Textures proposed for it: {sh['textures'] or 'none'}")
    opts = "; ".join(f"{k} = {v}" for k, v in ROT_OPTS.items())
    return (f"{q['truth']} {q['ability']}: does the ringed icon turn with its placement or stay upright?\n"
            f"{opts}; U = unsure.\nThe evaluation named these right; the fit chose rotations "
            f"{sh['fit_rotations']} over {sh['n_right']} right crops (a symmetric glyph fits any).")


def answer_text(q: dict, ch: str) -> str | None:
    if q["kind"] == "texture":
        if ch in "1234":
            present = [s for s in SLOTS if q["agent"] and (q["agent"], s) in ev.GLYPHS]
            i = int(ch) - 1
            return f"{q['agent']}:{present[i]}" if i < len(present) else None
        return {"5": "agent_other", "6": "not_ability"}.get(ch)
    if q["kind"] == "visibility":
        return {"1": "icon", "2": "shape", "3": "icon_and_shape", "4": "nothing"}.get(ch)
    return {"1": "rotates", "2": "upright", "3": "fixed_orientations"}.get(ch)


# ------------------------------------------------------------------ storage

def answered() -> dict:
    """The last answer per key, as written. No answer stands for another key: a view's answer never settles
    another view [domain:abilities/views-separate-per-ability] (0.1.0 carried a teammate's answer to the retired
    `drawing` key; 0.2.0 does not)."""
    last = {}
    if ANSWERS.exists():
        for line in ANSWERS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
    return last


def settled(done: dict, reask_unsure: bool = False) -> dict:
    """The keys the ask loop skips: every answered key, less the unsure ones when `reask_unsure`."""
    return {k: r for k, r in done.items() if not (reask_unsure and r.get("unsure"))}


def seconds_per_answer(path: Path = ANSWERS, max_gap_s: float = 120.0) -> dict:
    """{kind: median seconds between consecutive answers of one kind by this tool}, gaps over `max_gap_s` (a
    break) left out: the measured pace the time estimate uses."""
    gaps, prev = defaultdict(list), None
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if not str(r.get("tool", "")).startswith("ask-minimap-glyphs"):
                prev = None
                continue
            t = datetime.datetime.fromisoformat(r["ts"])
            if prev and prev[0] == r["kind"] and 0 < (t - prev[1]).total_seconds() <= max_gap_s:
                gaps[r["kind"]].append((t - prev[1]).total_seconds())
            prev = (r["kind"], t)
    return {k: float(np.median(v)) for k, v in gaps.items()}


def view_differences(done: dict) -> list[tuple]:
    """Abilities where the player's sure teammate's and enemy's answers differ. Views are separate per ability
    [domain:abilities/views-separate-per-ability], so each is a recorded view difference: a fact about that
    ability, listed beside the view facts, never a conflict to resolve."""
    out = []
    for k, r in done.items():
        if not (k.startswith("visibility:") and k.endswith(":ally")) or r.get("unsure"):
            continue
        e = done.get(k[:-len(":ally")] + ":enemy")
        if e and not e.get("unsure") and (e.get("answer"), e.get("other")) != (r.get("answer"), r.get("other")):
            out.append((k[len("visibility:"):-len(":ally")], r.get("answer"), r.get("other"), e.get("answer"),
                        e.get("other")))
    return sorted(out)


def append(row: dict) -> None:
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    with open(ANSWERS, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


# ------------------------------------------------------------------ UI

def ask_loop(qs: list[dict], z, by: str, reask_unsure: bool = False) -> None:
    import tkinter as tk
    from tkinter import simpledialog

    from PIL import Image, ImageTk

    done = settled(answered(), reask_unsure)
    todo = [q for q in qs if q["key"] not in done]
    if not todo:
        print(f"all {len(qs)} questions answered ({ANSWERS})")
        return
    root = tk.Tk()
    root.title(f"{VERSION}: minimap glyph questions")
    img_lbl = tk.Label(root, bg="black")
    img_lbl.pack(padx=6, pady=6)
    txt = tk.Label(root, justify="left", anchor="w", wraplength=1100, font=("Segoe UI", 11))
    txt.pack(fill="x", padx=8)
    status = tk.Label(root, anchor="w", fg="grey")
    status.pack(fill="x", padx=8, pady=(0, 6))
    st = {"i": 0, "photo": None}

    def show():
        if st["i"] >= len(todo):
            root.destroy()
            return
        q = todo[st["i"]]
        rgb = cv2.cvtColor(panel(q, z), cv2.COLOR_BGR2RGB)
        st["photo"] = ImageTk.PhotoImage(Image.fromarray(rgb))   # keep a reference or Tk blanks it
        img_lbl.configure(image=st["photo"])
        txt.configure(text=prompt(q))
        status.configure(text=f"{st['i'] + 1} / {len(todo)} unanswered ({len(qs)} in all)   {q['key']}   "
                              f"A back, U unsure, Q/ESC save and quit")

    def record(q, answer, unsure=False, other=None):
        append({"key": q["key"], "kind": q["kind"], "answer": answer, "unsure": unsure, "other": other, "by": by,
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tool": VERSION,
                "inventory_version": ev.INVENTORY_VERSION, "build": ev.BUILD, "shown": q["shown"],
                "compared_against_derived": q["kind"] == "texture"})

    def key(ev_):
        ch = (ev_.char or "").lower()
        if ev_.keysym == "Escape" or ch == "q":
            root.destroy()
            return
        if st["i"] >= len(todo):
            return
        q = todo[st["i"]]
        if ch == "a":
            st["i"] = max(0, st["i"] - 1)
            show()
            return
        if ch == "u":
            record(q, None, unsure=True)
        elif ch == "7":
            s = simpledialog.askstring("other", "Your answer, in words:", parent=root)
            if not s:
                return
            record(q, "other", other=s)
        else:
            a = answer_text(q, ch)
            if a is None:
                return
            record(q, a)
        st["i"] += 1
        show()

    root.bind("<Key>", key)
    show()
    root.mainloop()
    print(f"answers in {ANSWERS}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kinds", default="texture,visibility,rotation")
    ap.add_argument("--by", default="player")
    ap.add_argument("--out", default=str(ev.OUT))
    ap.add_argument("--list", action="store_true", help="print the questions and write nothing")
    ap.add_argument("--reask-unsure", action="store_true", help="ask again the keys answered unsure")
    args = ap.parse_args()
    out = Path(args.out)
    inv = json.load(open(out / "inventory.json", encoding="utf-8"))
    d, z = ev.load_scores(out)
    check_facts()
    kinds = args.kinds.split(",")
    qs, vis_pruned = [], []
    if "texture" in kinds:
        qs += texture_questions(inv)
    if "visibility" in kinds:
        qs += visibility_questions(inv, vis_pruned, gamedata_views())
    if "rotation" in kinds:
        qs += rotation_questions(d)
    if args.list:
        done = settled(answered(), args.reask_unsure)
        for q in qs:
            print(("done " if q["key"] in done else "open ") + q["key"])
        by_fact, glance = texture_pruned(inv)
        print("\nTextures a domain fact answers (not asked):")
        for stem, fact in by_fact:
            print(f"  {stem:44s} [domain:{fact}]")
        print("\nTo glance at, not ask: textures whose only evidence of being a HUD minimap marker is their name "
              f"(best labelled-crop correlation < {LABEL_EVIDENCE}, best DisplayIcon correlation < {ICON_EVIDENCE}):")
        for stem, agent, ic, lc in glance:
            print(f"  {stem:44s} {str(agent):9s} icon {ic}  labels {lc}")
        print(f"\nVisibility: {len(vis_pruned)} abilities whose caster view the sheet decides ask nothing "
              f"({', '.join('[domain:' + f + ']' for f in VIEW_FACTS)})")
        dis = view_differences(done)
        print(f"\nRecorded view differences: the player's teammate's and enemy's answers differ on {len(dis)} "
              "abilities (views are separate per ability [domain:abilities/views-separate-per-ability]; "
              "a difference is a fact, not a conflict):")
        for row in dis:
            print("  " + " | ".join(str(x) for x in row))
        opened = {k: sum(q["kind"] == k and q["key"] not in done for q in qs) for k in ("texture", "visibility",
                                                                                      "rotation")}
        print("open:", opened)
        if "visibility" in kinds:
            print("open visibility by view:", {v: sum(q["kind"] == "visibility" and q["view"] == v and q["key"] not in
                                                      done for q in qs) for v in VIEWS})
        pace = seconds_per_answer()
        est = sum(n * pace.get(k, 10.0) for k, n in opened.items())
        print(f"estimate: {est / 60:.0f} min at the measured median pace {({k: round(v, 1) for k, v in pace.items()})}"
              " s per answer (10 s where unmeasured)")
        print({k: sum(q["kind"] == k for q in qs) for k in ("texture", "visibility", "rotation")},
              {"texture_by_fact": len(by_fact), "texture_glance": len(glance), "visibility_decided": len(vis_pruned)})
        return
    ask_loop(qs, z, args.by, args.reask_unsure)


if __name__ == "__main__":
    main()
