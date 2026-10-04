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
  and no view's answer settles another's. A view is settled by the player's
  own answer to that view's key; by a domain fact the player gave
  (`VIEW_STATEMENT_FACTS`, `known = "player"`) that names the view and fixes
  icon and shape, unless the player answered that view, as
  [domain:abilities/killjoy-lockdown-global-minimap] settles Lockdown's
  caster view (the player's own answers settle its teammate and enemy views,
  and agree with it); or, for `self` alone, by a sheet Minimap
  cell (the caster's view) that carries a domain fact and no `?`, census
  vote, split or "disputed". A player fact or the player's words under
  another key (`STATEMENT_ROWS`) that contradicts an answer reopens the key,
  both statements shown, until the player answers with them in view: the
  player's sure "icon and shape" for Blaze's teammate and enemy views
  reopens, contradicted by [domain:abilities/phoenix-blaze-no-minimap-icon].
  `--list` prints the open keys first, each reopened one with its reason,
  then the views the facts settle. The spectator view is not asked: the
  player believes it is the self view less the audio circle
  [domain:minimap/spectator-view-matches-self]. The `drawing` answers given
  under the retired prompt, which said all views draw alike, settle no view.
  Order: reopened keys first; then abilities with a proposed texture, then
  those the game data (`ability-states-gamedata-0.2.0`) gives a minimap
  drawing, then the rest;
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

VERSION = "ask-minimap-glyphs-0.3.1"
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
    if "disputed" in cell:
        return "a disputed statement"
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


ALL_VIEWS = tuple(VIEWS)
#: What a domain fact the player gave (`known = "player"`) states about an ability's minimap views:
#: fact -> [(agent, slot, ability, views, states, words)]. `views` names the views the claim states explicitly, or
#: None when the claim says only "on the minimap" and names no view. `states` holds what the claim says is drawn:
#: `icon`, `shape` and `drawn`, each True or False; a key the claim leaves open is absent. `words` quotes, for each
#: state and for `views`, the claim's own words that state it; `check_facts` finds each quote in the claim and
#: checks it against `STATE_WORDS` and `VIEW_WORDS`. A statement settles a view only when it names that view and
#: fixes both `icon` and `shape` (or says nothing is drawn), and the player has not answered that view; any other
#: statement settles nothing but is shown with the question and checked against the player's answers. Each row
#: reads its own fact's claim, never another ability's [domain:abilities/ability-rules-are-unique].
VIEW_STATEMENT_FACTS = {
    "abilities/killjoy-lockdown-global-minimap": [
        ("Killjoy", "X", "Lockdown", ALL_VIEWS, {"icon": True, "shape": True},
         {"views": "drawn on every player's minimap", "icon": "the device's position", "shape": "a large ring"})],
    "abilities/clove-rouse": [
        ("Clove", "E", "Ruse", ("self",), {"shape": True},
         {"views": "drawn on the caster's minimap", "shape": "a bounded dark disc"}),
        *[("Clove", s, n, ("self",), {"drawn": False},
           {"views": "drawn on the caster's minimap",
            "drawn": "Ruse is the only Clove ability that draws anything there"})
          for s, n in (("C", "Pick-me-up"), ("Q", "Meddle"), ("X", "Not Dead Yet"))]],
    "abilities/phoenix-blaze-no-minimap-icon": [
        ("Phoenix", "C", "Blaze", None, {"icon": False, "shape": True},
         {"icon": "draws no icon on the minimap", "shape": "its minimap drawing is the wall"})],
    "abilities/phoenix-blaze": [
        ("Phoenix", "C", "Blaze", None, {"shape": True}, {"shape": "drawn as a smooth curve"})],
    "abilities/gekko-wingman-minimap-icon": [
        ("Gekko", "Q", "Wingman", ("ally", "enemy"), {"icon": True},
         {"views": "green for an ally Gekko and red for an enemy one", "icon": "on the minimap as an icon"})],
    "abilities/gekko-thrash-global-minimap": [
        ("Gekko", "X", "Thrash", ("enemy",), {"icon": True},
         {"views": "An enemy Gekko's Thrash", "icon": "can show its icon on the player's minimap"})],
    "abilities/sova-recon-bolt-minimap-ring": [
        ("Sova", "E", "Recon Bolt", None, {"icon": True, "shape": True},
         {"icon": "with the bolt's icon at the centre", "shape": "drawn on the minimap as a teal ring"})],
    "abilities/pulse-scan-abilities": [
        (a, s, n, None, {"shape": True}, {"shape": "All three draw a ring of their range on the minimap"})
        for a, s, n in (("Sova", "E", "Recon Bolt"), ("Fade", "E", "Haunt"), ("Tejo", "C", "Stealth Drone"))],
    "abilities/clove-dead-smoke-range-circle": [
        ("Clove", "E", "Ruse", ("ally",), {"shape": True},
         {"views": "Teammates see it on their minimaps", "shape": "the minimap draws a large circle"})],
    "abilities/sage-barrier-orb-global-minimap": [
        ("Sage", "C", "Barrier Orb", ALL_VIEWS, {"shape": True},
         {"views": "drawn on every player's minimap", "shape": "Barrier Orb wall"})],
    "abilities/deadlock-barrier-mesh-global-minimap": [
        ("Deadlock", "C", "Barrier Mesh", ALL_VIEWS, {"drawn": True},
         {"views": "drawn on every player's minimap", "drawn": "is drawn on every player's minimap"})],
    "abilities/sova-hunters-fury-global-minimap": [
        ("Sova", "X", "Hunter's Fury", ALL_VIEWS, {"shape": True},
         {"views": "lines on every player's minimap", "shape": "drawn as lines"})],
    "abilities/brimstone-orbital-strike-global-minimap": [
        ("Brimstone", "X", "Orbital Strike", ALL_VIEWS, {"shape": True},
         {"views": "on every player's minimap", "shape": "drawn as a hazard circle"})],
    "abilities/astra-cosmic-divide-global-minimap": [
        ("Astra", "X", "Astral Form / Cosmic Divide", ALL_VIEWS, {"shape": True},
         {"views": "across every player's minimap", "shape": "Cosmic Divide wall"})],
    "abilities/viper-toxic-screen-global-minimap": [
        ("Viper", "E", "Toxic Screen", ALL_VIEWS, {"shape": True},
         {"views": "drawn on every player's minimap", "shape": "Toxic Screen line"})],
    "abilities/reyna-leer-global-minimap": [
        ("Reyna", "C", "Leer", ("enemy",), {"drawn": True},
         {"views": "An enemy Reyna's Leer", "drawn": "is drawn on the player's minimap"})],
    "abilities/reyna-leer-enemy-minimap-glyph": [
        ("Reyna", "C", "Leer", ("enemy",), {"icon": True},
         {"views": "an enemy Reyna's Leer", "icon": "an iris, with a red vertical pupil"})],
    "abilities/fade-haunt-global-minimap": [
        ("Fade", "E", "Haunt", ("enemy",), {"drawn": True},
         {"views": "An enemy Fade's Haunt", "drawn": "is drawn on the player's minimap"})],
}
#: The word stems a quote must hold for each state it supports: (state, value) -> stems, matched at a word start.
#: A point marker at a position is read as an icon (Lockdown's "the device's position"), and Leer's iris and
#: pupil as its icon; both readings are arguable and stay visible here. A False state needs a negation or an
#: exclusion ("the only ... that draws"), and a True state's quote may hold none.
STATE_WORDS = {("icon", True): ("icon", "position", "iris"),
               ("shape", True): ("ring", "circle", "disc", "wall", "curve", "line"),
               ("drawn", True): ("drawn", "draws")}
NEGATIONS = ("no", "not", "nothing", "never", "only")
#: The words a `views` quote must hold: every view at once ("every player's"), or each named view's own word.
VIEW_WORDS = {"self": ("caster",), "ally": ("ally", "teammate"), "enemy": ("enemy",)}
#: The player's own statements recorded under another key of the answer file, by that key: (agent, slot, views,
#: states). "possible" is a hedge: shown with the question, never counted for or against an answer.
STATEMENT_ROWS = {
    "question:blaze-icon:enemy": ("Phoenix", "C", ("enemy",), {"icon": "possible"}),
    # "Does Sova's Recon Bolt ring show on the enemy team's minimap as well?" "Yes" (2026-10-04)
    "visibility:Sova:E:minimap-ring": ("Sova", "E", ("enemy",), {"shape": True}),
}
#: What each visibility answer states.
ANSWER_STATES = {"icon": {"icon": True, "shape": False}, "shape": {"icon": False, "shape": True},
                 "icon_and_shape": {"icon": True, "shape": True}, "nothing": {"icon": False, "shape": False}}


def check_facts(sheet: dict | None = None) -> None:
    """Every fact the pruning cites must exist; a renamed fact fails loudly. A view-statement fact must be the
    player's (`known = "player"`), name the ability the sheet keeps under its agent and slot, and quote the claim
    for every state and view it codes (`claim_mismatches`)."""
    from reticle import domain
    facts = domain.load()
    cited = list(TEXTURE_FACTS.values()) + list(VIEW_FACTS) + list(VIEW_STATEMENT_FACTS)
    missing = [k for k in cited if k not in facts]
    if missing:
        raise SystemExit(f"domain facts missing: {missing}")
    not_player = [k for k in VIEW_STATEMENT_FACTS if facts[k].known != "player"]
    if not_player:
        raise SystemExit(f"view-statement facts not known = player: {not_player}")
    sheet = sheet_minimap() if sheet is None else sheet
    wrong = [(k, a, s, n, sheet.get((a, s), ("absent",))[0]) for k, rows in VIEW_STATEMENT_FACTS.items()
             for a, s, n, *_ in rows if " ".join(sheet.get((a, s), ("",))[0].split()) != n]
    if wrong:
        raise SystemExit(f"view-statement rows name another ability than the sheet: {wrong}")
    bad = claim_mismatches(facts)
    if bad:
        raise SystemExit("view-statement rows the claim text does not support:\n  " + "\n  ".join(bad))


def _quote_holds(text: str, stems: tuple) -> bool:
    return any(re.search(r"\b" + re.escape(w), text, flags=re.I) for w in stems)


def claim_mismatches(facts: dict, table: dict | None = None) -> list[str]:
    """Where a view-statement row's coded states or views disagree with its fact's claim text: a state or a named
    view without a quote, a quote the claim does not hold, a quote without the words `STATE_WORDS` or
    `VIEW_WORDS` ask for that state or view, a False state quoted without a negation (`NEGATIONS`) or a True
    state quoted with one. A row without quotes fails. The check reads words, not meaning: it catches a row that
    drifts from its claim, not a claim the words mislead."""
    out = []
    for key, rows in (VIEW_STATEMENT_FACTS if table is None else table).items():
        claim = " ".join(facts[key].claim.split()).lower()
        for row in rows:
            agent, slot, _, views, states, *rest = row
            words, at = (rest[0] if rest else {}), f"{key} {agent}:{slot}"
            for k, v in states.items():
                q = words.get(k)
                if not q:
                    out.append(f"{at}: {k}={v} quotes no claim words")
                    continue
                if " ".join(q.split()).lower() not in claim:
                    out.append(f"{at}: {k} quote not in the claim: {q!r}")
                if v is True and not _quote_holds(q, STATE_WORDS[(k, True)]):
                    out.append(f"{at}: {k}=True quote holds none of {STATE_WORDS[(k, True)]}: {q!r}")
                if (v is False) != _quote_holds(q, NEGATIONS):
                    out.append(f"{at}: {k}={v} quote {'lacks' if v is False else 'holds'} a negation: {q!r}")
            if views:
                q = words.get("views")
                if not q:
                    out.append(f"{at}: views {list(views)} quote no claim words")
                    continue
                if " ".join(q.split()).lower() not in claim:
                    out.append(f"{at}: views quote not in the claim: {q!r}")
                if tuple(views) == ALL_VIEWS:
                    if "every player" not in q.lower():
                        out.append(f"{at}: all views quoted without 'every player': {q!r}")
                else:
                    out += [f"{at}: view {v} quoted without {VIEW_WORDS[v]}: {q!r}" for v in views
                            if not _quote_holds(q, VIEW_WORDS[v])]
    return out


def norm_states(states: dict) -> dict:
    """The states a statement implies: nothing drawn means no icon and no shape; an icon or a shape is a drawing."""
    d = dict(states)
    if d.get("drawn") is False:
        d.setdefault("icon", False)
        d.setdefault("shape", False)
    if d.get("icon") is True or d.get("shape") is True:
        d.setdefault("drawn", True)
    if d.get("icon") is False and d.get("shape") is False:
        d.setdefault("drawn", False)
    return d


def clash(a: dict, b: dict) -> list[str]:
    """The keys two statements both fix, as True or False, to different values; a hedge fixes nothing."""
    a, b = norm_states(a), norm_states(b)
    return [k for k in ("icon", "shape", "drawn") if isinstance(a.get(k), bool) and isinstance(b.get(k), bool)
            and a[k] != b[k]]


def category(states: dict) -> str | None:
    """The visibility answer a statement fixes in full, or None when it leaves icon or shape open."""
    d = norm_states(states)
    for name, st in ANSWER_STATES.items():
        if all(d.get(k) is v for k, v in st.items()):
            return name
    return None


def fact_statements(facts: dict | None = None, table: dict | None = None) -> dict:
    """{(agent, slot): [statement]} from the player's view-statement facts. A statement carries its citation
    token, date, views (None: no view named), the claim's words and what it states."""
    if facts is None:
        from reticle import domain
        facts = domain.load()
    out = defaultdict(list)
    for key, rows in (VIEW_STATEMENT_FACTS if table is None else table).items():
        f = facts[key]
        for agent, slot, _, views, states, *_ in rows:
            out[(agent, slot)].append({"source": f"[domain:{key}]", "by": f.known, "since": f.since,
                                       "views": list(views) if views else None,
                                       "says": " ".join(f.claim.split())[:300], "states": states})
    return out


def row_statements(done: dict) -> dict:
    """{(agent, slot): [statement]} from the player's answers under other keys (`STATEMENT_ROWS`)."""
    out = defaultdict(list)
    for key, (agent, slot, views, states) in STATEMENT_ROWS.items():
        r = done.get(key)
        if r is None:
            continue
        words = r.get("answer_words") or r.get("player_words") or r.get("answer")
        asked = (r.get("shown") or {}).get("question")
        words = f"{asked} {words}" if asked else words
        out[(agent, slot)].append({"source": f"answers.jsonl#L{r.get('_line', '?')} {key}", "by": r.get("by"),
                                   "since": r.get("ts"), "views": list(views), "says": str(words)[:300],
                                   "states": states})
    return out


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


def visibility_questions(inv: dict, pruned: list | None = None, gd: dict | None = None,
                         stmts: dict | None = None) -> list[dict]:
    """One question per ability and view (self, teammate as `ally`, enemy) that nothing settles. Views are separate
    per ability [domain:abilities/views-separate-per-ability]: no view's answer settles another's. The sheet's
    Minimap cell is the caster's view, so a decided cell settles `self` alone (listed in `pruned`); a player's
    answer to a view's key settles that view through the ask loop's answered keys. The game data (`gd`) orders
    the abilities and annotates the prompt; it answers nothing. `stmts` ({(agent, slot): [statement]}, from
    `fact_statements` and `row_statements`) go with each view they bear on, as `shown["statements"]`; `review`
    settles or reopens a view from them."""
    sheet = sheet_minimap()
    stmts = stmts or {}
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
                                 "game_data": gamedata_note(gd, agent, slot, view),
                                 "statements": [s for s in stmts.get((agent, slot), [])
                                                if s["views"] is None or view in s["views"]]}})
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
        said = "".join(f"\n  {s['source']} ({s['by']}, {str(s['since'])[:16]}): {s['says'][:200]}"
                       for s in sh.get("statements") or [])
        reopened = f"\nREOPENED: {sh['reopened']}" if sh.get("reopened") else ""
        return (f"{q['agent']} {q['slot']} {q['ability']}, {VIEWS[q['view']][1].upper()} VIEW: what does it draw on "
                f"{VIEWS[q['view']][1]} minimap while it is out? (Views are separate per ability; answer this "
                f"view alone.)\n{opts}; U = unsure.\nAsked because: {sh['why_asked']}.{cell}{reopened}\n"
                + (f"The player's statements on this view:{said}\n" if said else "") +
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
        for i, line in enumerate(ANSWERS.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                r = json.loads(line)
                r["_line"] = i            # in memory only: the row's line, cited when a statement contradicts it
                last[r["key"]] = r
    return last


def settled(done: dict, reask_unsure: bool = False) -> dict:
    """The answered keys the ask loop may skip: every answered key, less the unsure ones when `reask_unsure`.
    `review` reopens any of them a statement contradicts."""
    return {k: r for k, r in done.items() if not (reask_unsure and r.get("unsure"))}


def review(q: dict, done: dict) -> tuple[bool, str]:
    """(open, why) for one question, given the answers the ask loop may skip (`settled`).

    A visibility view stays open, its answer notwithstanding, while a statement in `shown["statements"]` (a
    player's fact, or the player's own words under another key) fixes icon, shape or drawn otherwise than the
    answer does and the answer was given without that statement shown: the player said two things, and the
    question shows both. An answer given with the contradicting statements shown stands. Unanswered, the view is
    open while two statements contradict each other, settled when a statement naming this view fixes the answer
    in full, open otherwise. A hedge ("possible") fixes nothing."""
    row = done.get(q["key"])
    stmts = (q.get("shown") or {}).get("statements") or []
    if q["kind"] != "visibility":
        return (row is None, "answered" if row else "no answer")
    if row is not None:
        said = {} if row.get("unsure") else ANSWER_STATES.get(row.get("answer"), {})
        against = [s for s in stmts if clash(said, s["states"])]
        seen = {s.get("source") for s in ((row.get("shown") or {}).get("statements") or [])}
        unseen = [s for s in against if s["source"] not in seen]
        if unseen:
            ans = row.get("answer") if row.get("answer") != "other" else f"other: {row.get('other')}"
            return True, ("contradiction: the answer " + f"'{ans}' (answers.jsonl#L{row.get('_line', '?')}, "
                          f"{str(row.get('ts'))[:16]}) against " + "; ".join(
                              f"{s['source']} ({s['by']}, {str(s['since'])[:16]}, on {', '.join(clash(said, s['states']))}): "
                              f"{s['says'][:160]}" for s in unseen))
        return False, ("answered with the contradicting statements shown" if against else "answered")
    pairs = [(a, b) for i, a in enumerate(stmts) for b in stmts[i + 1:] if clash(a["states"], b["states"])]
    if pairs:
        return True, "statements disagree: " + "; ".join(f"{a['source']} against {b['source']}" for a, b in pairs)
    for s in stmts:
        if s["views"] and q["view"] in s["views"] and category(s["states"]):
            return False, f"settled by {s['source']}: {category(s['states'])}"
    return True, "no answer"


def annotate(qs: list[dict], done: dict) -> dict:
    """{key: (open, why)} for every question; a reopened question carries the reason in `shown["reopened"]`, so
    the answer row records what the player saw. Reopened questions go first, in their prior order."""
    out = {}
    for q in qs:
        out[q["key"]] = review(q, done)
        if out[q["key"]][0] and out[q["key"]][1] != "no answer" and q["kind"] == "visibility":
            q["shown"]["reopened"] = out[q["key"]][1]
    qs.sort(key=lambda q: 0 if q["shown"].get("reopened") else 1)
    return out


def key_lines(qs: list[dict], status: dict) -> list[str]:
    """`--list`'s key lines: every open key in asking order, a reopened one with its reason, then the done keys."""
    lines = []
    for q in qs:
        is_open, why = status[q["key"]]
        if is_open:
            lines.append("open " + q["key"] + ("" if why == "no answer" else f"   <- {why}"))
    return lines + ["done " + q["key"] for q in qs if not status[q["key"]][0]]


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

    status = annotate(qs, settled(answered(), reask_unsure))
    todo = [q for q in qs if status[q["key"]][0]]
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
    stmts = fact_statements()
    for k, v in row_statements(answered()).items():
        stmts[k] = stmts.get(k, []) + v
    if "texture" in kinds:
        qs += texture_questions(inv)
    if "visibility" in kinds:
        qs += visibility_questions(inv, vis_pruned, gamedata_views(), stmts)
    if "rotation" in kinds:
        qs += rotation_questions(d)
    if args.list:
        done = settled(answered(), args.reask_unsure)
        status = annotate(qs, done)
        print("Open keys first, in asking order; a reopened key prints why:")
        print("\n".join(key_lines(qs, status)))
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
        by_stmt = [(q["key"], status[q["key"]][1]) for q in qs if status[q["key"]][1].startswith("settled by")]
        print(f"\nViews a player fact settles (it names the view and fixes icon and shape; not asked): {len(by_stmt)}")
        for k, why in by_stmt:
            print(f"  {k:36s} {why}")
        stood = [q["key"] for q in qs if status[q["key"]][1] == "answered with the contradicting statements shown"]
        print(f"\nAnswers the player gave against a statement shown with the question (the answer stands; the "
              f"statement may need revising): {len(stood)}")
        for k in stood:
            print("  " + k)
        opened = {k: sum(q["kind"] == k and status[q["key"]][0] for q in qs) for k in ("texture", "visibility",
                                                                                     "rotation")}
        print("\nopen:", opened, " reopened on a contradiction:",
              sum(1 for q in qs if status[q["key"]][1].startswith(("contradiction", "statements disagree"))))
        if "visibility" in kinds:
            print("open visibility by view:", {v: sum(q["kind"] == "visibility" and q["view"] == v and
                                                      status[q["key"]][0] for q in qs) for v in VIEWS})
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
