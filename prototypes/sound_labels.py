r"""Turn the player's free-text sound names into structured labels.

    .\.venv\Scripts\python.exe prototypes\sound_labels.py [--tag T ...]

Why this exists
---------------
`sound_demo.py review` offers an `other` class with a free-text name, so an
unlisted sound is never forced into a listed class. On the second range clip
(session 9eb0960b1eff, `C:\Users\grant\Videos\2026-09-30 13-15-03.mp4`) the
player used it for 63 of 250 answers: Iso's abilities by phase ("iso
contingency fade out", "iso kill contract equip (phase 2)"), "nothing" and
"silent", and descriptions of where a window sits. The phases are the ones
[domain:abilities/ability-sound-phases] names; Iso's per ability are
[domain:abilities/iso-contingency-sound-phases],
[domain:abilities/iso-undercut-sound-phases],
[domain:abilities/iso-double-tap-sound-phases] and
[domain:abilities/iso-kill-contract-sound-phases].

What it does
------------
It reads each clip's labels file (`<store>/labels/sound_demo_<tag>.jsonl`),
takes the last answer per candidate as `sound_demo` does, and writes a derived
file beside it, `sound_demo_<tag>.structured-<VERSION>.jsonl`. The labels file
is never written. Each output row links its source row (file, 1-based line,
the row's `at`) and carries:

- `kind`: `sound` (one class), `no_sound` (the player heard nothing: negative
  evidence for every class), `compound` (two sounds at once), `ability_no_phase`
  (an ability named without a phase), `unmapped` (no rule applies), or
  `excluded` (not an accept or relabel);
- `cls`, `subject`, `phase`, `part`, `context`, and `rule`, the rule that fired.

The parser is a fixed list of anchored patterns over the lowercased name; the
first that matches the whole name wins. An answer that hedges (might, maybe,
guess, not sure, don't think, echo, or a question mark) or that no rule covers
is `unmapped` and is listed, never guessed. "Nothing" and "silent" become
`no_sound` only when the whole name is a no-sound phrase, optionally with a
place ("in between, silent", "right before iso ability is cast, i don't hear
anything"). Contingency, Undercut, Double Tap and Kill Contract are Iso's, the
only agent the clip plays, so a name without "iso" still names Iso.

The first clip's names (session a01863947bab) go through the same rules;
`sound_bank.py` 0.1.0 keeps its own reading of them unchanged.

This is a prototype; nothing in `reticle/` uses it. `sound_bank2.py` reads
its output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

VERSION = "sound-labels-0.1.0"
STORE = Path.home() / "reticle-store"
LABELS = STORE / "labels"
TAGS = ("20260929", "20260930")
GUNS = ("ghost", "sheriff", "bandit", "spectre", "classic", "vandal", "phantom", "operator")
GUN_KINDS = ("equip", "single", "burst", "spray", "reload_empty", "reload_partial")
#: Iso's four abilities by the player's words; the clip plays Iso only.
ISO = {"contingency": "iso_contingency", "undercut": "iso_undercut",
       "double tap": "iso_double_tap", "kill contract": "iso_kill_contract"}
#: The player's phase words onto [domain:abilities/ability-sound-phases]'s phases.
PHASES = {"equip": "equip", "cast": "cast", "fade out": "fadeout", "fadeout": "fadeout",
          "fade-out": "fadeout", "running": "ongoing", "ongoing": "ongoing", "channel": "ongoing",
          "channeled": "ongoing", "channelled": "ongoing"}
MOVES = {"step": "footstep", "footstep": "footstep", "jump": "jump", "landing": "land", "land": "land"}
HEDGE = re.compile(r"\b(might|maybe|guess|not sure|don'?t think|echo|probably)\b|\?")
NOTHING = r"(?:nothing|silent|no sound|sounds like nothing|i don'?t hear anything)"
_ab = "|".join(sorted(map(re.escape, ISO), key=len, reverse=True))
_ph = "|".join(sorted(map(re.escape, PHASES), key=len, reverse=True))
ABILITY = re.compile(rf"^(?:iso )?({_ab}) ({_ph})(?: \(phase (\d)\))?$")
NO_SOUND = re.compile(rf"^{NOTHING}$")
NO_SOUND_AFTER = re.compile(rf"^{NOTHING},? (.+)$")          # "sounds like nothing, right after landing"
NO_SOUND_BEFORE = re.compile(rf"^(.+?),? \(?{NOTHING}\)?$")   # "in between, silent", "escape menu (...)"
SILENT_MOVE = re.compile(r"^silent (landing|step|jump)$")
BUY_CLOSE = re.compile(r"^buy menu clos(?:e|ing)$")
COMPOUND = re.compile(r"^it'?s (\w+)ing the (\w+) and (\w+)ing the (\w+)\b")
VERB = {"equipp": "equip", "dropp": "drop", "pick": "pickup", "reload": "reload"}


def norm(text: str) -> str:
    t = text.strip().lower().replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", t).rstrip(".")


def parse_name(name: str) -> dict:
    """One free-text `other_name` -> a structured reading. Deterministic: the
    first rule whose pattern matches the whole normalised name wins."""
    t = norm(name)
    if m := ABILITY.match(t):
        subj, ph = ISO[m.group(1)], PHASES[m.group(2)]
        part = int(m.group(3)) if m.group(3) else None
        cls = f"{subj}_{ph}" + (f"_{part}" if part else "")
        return {"kind": "sound", "cls": cls, "subject": subj, "phase": ph, "part": part, "rule": "ability_phase"}
    if HEDGE.search(t):
        return {"kind": "unmapped", "rule": "hedged"}
    if NO_SOUND.match(t):
        return {"kind": "no_sound", "rule": "no_sound"}
    if m := SILENT_MOVE.match(t):
        return {"kind": "no_sound", "context": MOVES[m.group(1)], "rule": "silent_move"}
    if m := NO_SOUND_AFTER.match(t):
        return {"kind": "no_sound", "context": m.group(1), "rule": "no_sound_then_place"}
    if m := NO_SOUND_BEFORE.match(t):
        return {"kind": "no_sound", "context": m.group(1), "rule": "place_then_no_sound"}
    if BUY_CLOSE.match(t):
        return {"kind": "sound", "cls": "buy_menu_close", "subject": "buy_menu", "phase": "close",
                "rule": "buy_menu_close"}
    if t in MOVES:
        return {"kind": "sound", "cls": MOVES[t], "subject": "movement", "phase": MOVES[t], "rule": "move_word"}
    if (m := COMPOUND.match(t)) and m.group(1) in VERB and m.group(3) in VERB:
        parts = [{"subject": m.group(2), "phase": VERB[m.group(1)]},
                 {"subject": m.group(4), "phase": VERB[m.group(3)]}]
        return {"kind": "compound", "parts": parts, "rule": "compound_two_verbs"}
    return {"kind": "unmapped", "rule": "no_rule"}


def parse_label(label: str) -> dict:
    """A listed class -> subject and phase (the class itself is kept as given)."""
    for g in GUNS:
        for k in GUN_KINDS:
            if label == f"{g}_{k}":
                return {"kind": "sound", "cls": label, "subject": g, "phase": k, "rule": "listed_gun"}
    for a in ISO.values():
        if label == a:
            return {"kind": "ability_no_phase", "subject": a, "rule": "listed_ability_no_phase"}
    return {"kind": "sound", "cls": label, "subject": label, "phase": None, "rule": "listed"}


def structure(tag: str) -> dict:
    src = LABELS / f"sound_demo_{tag}.jsonl"
    last: dict[str, tuple[int, dict, str]] = {}
    for ln, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            last[row["key"]] = (ln, row, line)
    out = []
    for key, (ln, r, line) in sorted(last.items(), key=lambda kv: kv[1][1]["span_ms"][0]):
        if r["answer"] not in ("accept", "relabel"):
            p = {"kind": "excluded", "rule": f"answer_{r['answer']}"}
        elif r["label"] == "other":
            p = parse_name(r.get("other_name") or "")
        else:
            p = parse_label(r["label"])
        out.append({"key": key, "session_id": r["session_id"], "t0": r["span_ms"][0] / 1000.0,
                    "t1": r["span_ms"][1] / 1000.0, "label": r["label"], "other_name": r.get("other_name"),
                    "variant": r.get("variant"), "note": r.get("note"),
                    "cls": None, "subject": None, "phase": None, "part": None, "context": None, **p,
                    "source": {"file": str(src), "line": ln, "at": r.get("at"),
                               "sha1": hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]},
                    "version": VERSION})
    dst = LABELS / f"sound_demo_{tag}.structured-{VERSION}.jsonl"
    if dst == src:
        raise SystemExit("refusing to write over the labels file")
    dst.write_text("".join(json.dumps(x) + "\n" for x in out), encoding="utf-8")
    counts = Counter(x["kind"] for x in out)
    others = [x for x in out if x["label"] == "other"]
    rules = Counter(x["rule"] for x in others)
    unm = [x for x in out if x["kind"] in ("unmapped", "ability_no_phase")]
    print(f"{tag}: {len(out)} candidates -> {dst}\n  kinds {dict(counts)}\n  'other' names by rule {dict(rules)}")
    for x in unm:
        print(f"  UNMAPPED {x['key']} {x['t0']:.2f} s [{x['rule']}] label={x['label']} "
              f"name={x['other_name']!r}")
    return {"tag": tag, "path": str(dst), "kinds": dict(counts), "other_rules": dict(rules),
            "unmapped": [{"key": x["key"], "t0": x["t0"], "rule": x["rule"], "label": x["label"],
                          "other_name": x["other_name"]} for x in unm]}


def load(tag: str) -> list[dict]:
    p = LABELS / f"sound_demo_{tag}.structured-{VERSION}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", action="append", choices=TAGS)
    a = ap.parse_args(argv)
    for tag in a.tag or TAGS:
        structure(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
