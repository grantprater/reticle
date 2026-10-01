"""Which abilities can draw a killfeed icon, per agent, from the reference's
ability descriptions. Owns [owns:killfeed-kits].

    .\\.venv\\Scripts\\python.exe -m reticle.adjudication.killfeed_kits [--store PATH] [--check]

The player's rule: any damaging ability can draw a kill's weapon-slot icon
[domain:killfeed/damaging-ability-kill-icon], and any disabling ability can
draw an assist icon in the panel left of the killer
[domain:killfeed/disabling-ability-assist-icon]. Mechanics are unique per
ability [domain:abilities/ability-rules-are-unique], so each ability is
decided from its own description in `<store>/reference/abilities.json` (the
valorant-api dump with the wiki harvest), or from a killfeed fact that names
its icon; never by analogy with another ability.

The player's answers (`PLAYER_ANSWERS`, 2026-10-01) decide every ability
the rule below left open, and a slot-Passive ability draws no icon
[domain:abilities/passive-abilities-draw-no-ui]; the rule's own decision is
kept beside the answer. The damage rule, in order:

1. A killfeed fact names the ability's weapon-slot icon (`FACT_ICONS`): in
   the kit.
2. The description qualifies a damage clause: it heals (`heal`), or
   deals damage only on a condition (`damage if`): undecided.
3. The description states a damage or kill clause (`DAMAGE_CLAUSES`):
   damaging.
4. The description uses a harm word (damage, kill, die, death, lethal,
   Decay) outside a clause, after the kill-count reset and use-after-death
   phrases (`NOT_HARM`) are struck: undecided.
5. The wiki function is Weapon Equip: undecided (a weapon with no stated
   damage).
6. The description describes an attack (fires at, shoots, explodes,
   detonates, blast, strikes) and names no status effect: undecided.
7. Otherwise: not damaging.

The disabling rule: the description names a status effect on others
(`STATUS_TERMS`: Blind, Concuss, Slow, Nearsight, Suppress, Detain, Deafen,
Decay, Vulnerable, Hinder, knock up or back, pull, crouch, jam, hold in place,
capture, smoke or vision block): disabling. A Reveal or a movement or bullet
barrier with no status term is undecided; anything else is not disabling.

An agent's kit (`kill_kits`) is its damaging abilities with its fact-named
icons. An agent with an undecided damage question (`open_questions`) has no
kit the weapon owner may trust; the questions are in
docs/ABILITY_MECHANICS_SHEET.md, "Killfeed icons". The derivation is stored
in `templates/killfeed_kits.json`, every ability with its status, the rule
that decided it and the excerpt it decided on; `--check` re-derives it from
the store's reference and reports a difference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

# 0.2.0 (2026-10-01): agents keyed by the lineup's spelling (KAY_O).
# 0.3.0 (2026-10-01): the player's answers (`PLAYER_ANSWERS`) decide the 21
# abilities the rule left open; slot-Passive abilities draw no icon.
KILLFEED_KITS_VERSION = "killfeed-kits-0.3.0"

DATA = Path(__file__).resolve().parent.parent / "templates" / "killfeed_kits.json"
REFERENCE = "reference/abilities.json"

#: The player's answer to the damage questions the rule left open, verbatim.
PLAYER_ANSWER_SOURCE = (
    "the player, 2026-10-01: \"Killjoy turret, phoenix blaze and hot hands, raze blast "
    "pack and boom bot. Iso kill contract might show the icon if he kills them in it, "
    "that's the only borderline one, nothing else does damage. Also heating up is "
    "phoenix's passive.\"")

#: Each answered ability, by (agent, name): `damaging`, `possible` (the
#: player's belief, unconfirmed: in the kit, so the agent qualifies only once
#: the gallery holds it) or `not_damaging`. Heating Up is a passive
#: [domain:abilities/passive-abilities-draw-no-ui], decided by slot.
PLAYER_ANSWERS = {
    ("Killjoy", "TURRET"): "damaging", ("Phoenix", "Blaze"): "damaging",
    ("Phoenix", "Hot Hands"): "damaging", ("Raze", "Blast Pack"): "damaging",
    ("Raze", "Boom Bot"): "damaging", ("Iso", "Kill Contract"): "possible",
    **{k: "not_damaging" for k in (
        ("Clove", "Pick-me-up"), ("Clove", "Meddle"), ("Cypher", "Spycam"),
        ("Fade", "Seize"), ("Fade", "Nightfall"), ("Iso", "Double Tap"),
        ("Reyna", "Devour"), ("Sage", "Healing Orb"), ("Sova", "Owl Drone"),
        ("Veto", "Chokehold"), ("Viper", "Poison Cloud"), ("Viper", "Toxic Screen"),
        ("Viper", "Viper's Pit"), ("Viper", "Toxic"))},
}

#: A passive draws no on-screen icon [domain:abilities/passive-abilities-draw-no-ui].
PASSIVE = {"status": "passive", "by": "fact:abilities/passive-abilities-draw-no-ui", "excerpt": None}

#: Abilities a killfeed fact names in the weapon slot, with the fact.
FACT_ICONS = {
    "Aftershock": "killfeed/ability-kill-icon",
    "Headhunter": "killfeed/chamber-gun-shaped-abilities",
    "Tour De Force": "killfeed/chamber-gun-shaped-abilities",
    "Blade Storm": "killfeed/jett-blade-storm-icon",
    "Resurrection": "killfeed/revive-entries",
    "Not Dead Yet": "killfeed/revive-entries",
    "NULL/cmd": "killfeed/kayo-downed-entry",
}

#: A clause stating that the ability deals damage or kills.
DAMAGE_CLAUSES = {
    "deals-damage": r"\bdeal(?:s|ing)?\b[^.]*?\bdamage\b",
    "does-damage": r"\bdoes\b[^.]*?\bdamage\b",
    "damages-targets": r"\bdamag(?:es|ing)\s+(?:\w+\s+){0,2}?(?:players|enemies|anyone|targets|swarm|explosions)\b",
    "for-damage": r"\bfor (?:\w+ )?damage\b",
    "that-damages": r"\b(?:that|which)\s+(?:\w+\s+and\s+)?damages\b",
    "kills-an-enemy": r"\bwill kill an enemy\b",
    "will-die": r"\bwill die\b",
    "deadly": r"\bdeadly\b",
}

#: Qualifiers that leave a damage clause undecided.
QUALIFIERS = {"heals": r"\bheal\w*", "conditional": r"\bdamage if\b"}

#: Phrases about kills by any means restoring a charge or a duration, and
#: about use after the caster's own death; struck before the harm-word check,
#: since they say nothing of the ability's damage.
NOT_HARM = [r"[^.]*\bevery two kills\b[^.]*", r"\b(?:does not )?recharge knives on a kill\b",
            r"\brefreshes with each kill\b", r"\bkills reset the duration[^.]*",
            r"\bafter death\b"]

HARM_WORDS = r"\b(?:damag\w*|kill\w*|die|death|lethal|decay\w*)\b"
ATTACK_WORDS = r"\b(?:fires? at|shoot\w*|explod\w*|explosive|detonat\w*|blast\w*|strikes?)\b"

#: Status effects on others: the disabling rule.
STATUS_TERMS = (r"\b(?:blind\w*|flash\b|concuss\w*|slow(?:s|ed|ing|ly)?\b(?!-)|nearsight\w*|"
                r"suppress\w*|detain\w*|deafen\w*|decay\w*|vulnerable|hinder\w*|"
                r"knock\w* (?:up|back)|pull\w*|crouch|jamm\w*|hold\w* (?:nearby )?enemies in place|"
                r"captures?|smoke\w*|block\w* vision|vision[- ]block\w*)")
ASSIST_UNCLEAR = (r"\b(?:reveal\w*|marked by|terror trails|barriers?|blocks? (?:bullets|character movement)|"
                  r"wall (?:trap|of energy)|places a wall|wall bursts)\b")


def _sentence(text: str, m: re.Match) -> str:
    """The sentence of `text` holding match `m`."""
    start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    end = text.find(".", m.end())
    return text[start:end + 1 if end >= 0 else len(text)].strip()


def _search(pattern: str, text: str) -> Optional[re.Match]:
    return re.search(pattern, text, re.IGNORECASE)


def damage_decision(name: str, description: str, functions: Optional[str]) -> dict:
    """{"status": damaging | not_damaging | undecided, "by", "excerpt"} for one
    ability, by the module's damage rule."""
    if name in FACT_ICONS:
        return {"status": "kit_icon", "by": f"fact:{FACT_ICONS[name]}", "excerpt": None}
    text = " ".join(description.split())
    clause = next(((k, m) for k, p in DAMAGE_CLAUSES.items() if (m := _search(p, text))), None)
    if clause:
        for q, p in QUALIFIERS.items():
            if m := _search(p, text):
                return {"status": "undecided", "by": f"rule:{q}",
                        "excerpt": _sentence(text, m), "question": f"damage clause with {q}"}
        return {"status": "damaging", "by": f"rule:{clause[0]}", "excerpt": _sentence(text, clause[1])}
    struck = text
    for p in NOT_HARM:
        struck = re.sub(p, " ", struck, flags=re.IGNORECASE)
    if m := _search(HARM_WORDS, struck):
        return {"status": "undecided", "by": "rule:harm-word", "excerpt": _sentence(struck, m),
                "question": f"'{m.group(0)}' with no damage clause"}
    if functions and "weapon equip" in functions.lower():
        return {"status": "undecided", "by": "rule:weapon-equip", "excerpt": text[:160],
                "question": "a weapon whose description states no damage"}
    if (m := _search(ATTACK_WORDS, text)) and not _search(STATUS_TERMS, text):
        return {"status": "undecided", "by": "rule:attack-no-effect", "excerpt": _sentence(text, m),
                "question": f"'{m.group(0)}' with no stated damage or status"}
    return {"status": "not_damaging", "by": "rule:no-damage-wording", "excerpt": None}


def assist_decision(description: str) -> dict:
    """{"status": disabling | not_disabling | undecided, "by", "excerpt"} for one
    ability, by the module's disabling rule."""
    text = " ".join(description.split())
    if m := _search(STATUS_TERMS, text):
        return {"status": "disabling", "by": "rule:status-term", "excerpt": _sentence(text, m)}
    if m := _search(ASSIST_UNCLEAR, text):
        return {"status": "undecided", "by": "rule:reveal-or-barrier", "excerpt": _sentence(text, m),
                "question": f"'{m.group(0)}' with no status effect"}
    return {"status": "not_disabling", "by": "rule:no-status-term", "excerpt": None}


def derive(reference: dict, reference_sha: Optional[str] = None) -> dict:
    """The stored derivation from the parsed reference: every ability's two
    decisions, then per agent the kit, the damage questions, the assist icons
    and the assist questions. Agents are keyed by the lineup's and the
    arbiter's spelling, the asset stem (`lineup.ASSET_TO_AGENT` inverted:
    KAY_O where the reference says KAY/O)."""
    from ..lineup import ASSET_TO_AGENT
    to_stem = {v: k for k, v in ASSET_TO_AGENT.items()}
    abilities, kits, opened, assists, assist_open, unconfirmed = [], {}, {}, {}, {}, {}
    for ref_agent in sorted(reference["agents"]):
        agent = to_stem.get(ref_agent, ref_agent)
        kits[agent], assists[agent] = [], []
        for ab in reference["agents"][ref_agent]["abilities"]:
            name, desc = ab["name"], ab.get("description") or ""
            if ab.get("slot") == "Passive":
                dmg = ast = PASSIVE
            else:
                dmg = damage_decision(name, desc, ab.get("functions"))
                ast = assist_decision(desc)
                answer = PLAYER_ANSWERS.get((agent, name)) or PLAYER_ANSWERS.get((ref_agent, name))
                if answer:
                    dmg = {"status": answer, "by": "player:2026-10-01",
                           "excerpt": PLAYER_ANSWER_SOURCE, "rule": dmg}
            abilities.append({"agent": agent, "key": ab.get("key"), "name": name,
                              "functions": ab.get("functions"), "damage": dmg, "assist": ast})
            if dmg["status"] in ("damaging", "kit_icon", "possible"):
                kits[agent].append(name)
            if dmg["status"] == "possible":
                unconfirmed.setdefault(agent, []).append(name)
            elif dmg["status"] == "undecided":
                opened.setdefault(agent, []).append(name)
            if ast["status"] == "disabling":
                assists[agent].append(name)
            elif ast["status"] == "undecided":
                assist_open.setdefault(agent, []).append(name)
    return {"about": ("Killfeed-capable abilities per agent, derived by "
                      "reticle/adjudication/killfeed_kits.py from the reference's ability "
                      "descriptions and the killfeed facts. `kits`: damaging abilities and "
                      "fact-named icons (weapon slot); `unconfirmed`: kit abilities the player "
                      "believes possible; `open`: abilities neither the rule nor the player has "
                      "decided; `assist_icons` and `assist_open`: the disabling rule, unused by "
                      "the weapon owner."),
            "version": KILLFEED_KITS_VERSION,
            "source": {"reference": REFERENCE, "harvested": reference.get("harvested"),
                       "sha256": reference_sha, **(reference.get("source") or {})},
            "rules": {"damage_clauses": DAMAGE_CLAUSES, "qualifiers": QUALIFIERS,
                      "not_harm": NOT_HARM, "harm_words": HARM_WORDS,
                      "attack_words": ATTACK_WORDS, "status_terms": STATUS_TERMS,
                      "assist_unclear": ASSIST_UNCLEAR, "fact_icons": FACT_ICONS,
                      "player_answers": {f"{a}/{n}": v for (a, n), v in PLAYER_ANSWERS.items()},
                      "player_answer_source": PLAYER_ANSWER_SOURCE},
            "kits": kits, "open": opened, "unconfirmed": unconfirmed, "assist_icons": assists, "assist_open": assist_open,
            "abilities": abilities}


def derive_from_store(store_root: str | Path) -> dict:
    path = Path(store_root) / REFERENCE
    raw = path.read_bytes()
    return derive(json.loads(raw), hashlib.sha256(raw).hexdigest()[:16])


@lru_cache(maxsize=1)
def load() -> dict:
    """The stored derivation (`templates/killfeed_kits.json`)."""
    return json.loads(DATA.read_text(encoding="utf-8"))


def kill_kits() -> dict[str, frozenset]:
    """{agent: the abilities that can draw its weapon-slot icon}, for every
    agent; an agent in `open_questions` has a kit the rule left incomplete."""
    return {a: frozenset(v) for a, v in load()["kits"].items()}


def open_questions() -> dict[str, frozenset]:
    """{agent: abilities the damage rule cannot decide}."""
    return {a: frozenset(v) for a, v in load()["open"].items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from ..store import DEFAULT_STORE
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--check", action="store_true", help="compare with the stored derivation; write nothing")
    a = ap.parse_args(argv)
    out = derive_from_store(a.store)
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if a.check:
        same = DATA.exists() and DATA.read_text(encoding="utf-8") == text
        print("killfeed kits: stored derivation is current" if same
              else "killfeed kits: stored derivation differs from the reference; rerun without --check")
        return 0 if same else 1
    DATA.write_text(text, encoding="utf-8", newline="\n")
    n = {}
    for ab in out["abilities"]:
        n[ab["damage"]["status"]] = n.get(ab["damage"]["status"], 0) + 1
        n["assist_" + ab["assist"]["status"]] = n.get("assist_" + ab["assist"]["status"], 0) + 1
    print(f"{DATA}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
