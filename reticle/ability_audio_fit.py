r"""Fit and evaluate the audio witness's parameter set from stored audio,
through the wired scorer (`adjudication.ability_audio`, which owns the
ownership entry `ability-audio`; this module is its fit tool).

    reticle ability-audio-fit --gate G.json [--supply SID=AGENT] [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --fit ROOT [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --calibrate ROOT [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --late-phase ROOT [--audio-dir DIR]
    reticle ability-audio-fit --gate-in G.json --eval ROOT [--json OUT] [--audio-dir DIR]

`--gate` computes the gate's verdicts (`ability_timeline.player_tray_casts`,
with the kit witness's spans) once per session with stored audio-gate
labels, and writes them with the stream stamps it read, so the fit and the
evaluation read one stored state while other runs rewrite the store. The
player's agent is the identity arbiter's; `--supply SID=AGENT` names it for
a session where the arbiter names none, and the snapshot records that basis.
`--audio-dir` names directories holding `features/<sid>.npz` and
`labels/<sid>.json` for sessions whose log-mel the store lacks; their stamps
say so. Decodes no video and no capture audio; the fit decodes the game's
reference files.

**The split** is `ability_audio.split_sessions`, declared before scoring:
per agent the sessions sorted by id, even positions dev and odd held; an
agent with one session split at its frame midpoint. Demos are always held.

**One whitener** is fitted on the background of every agent's dev sessions
(`ability_audio.fit_whitener`), so an agent with no own match (Omen,
Deadlock) is scored zero-shot from the game's files. **Thresholds** are each
class's level at one false fire per live minute over every dev session.

**The references** are the store's manifest (`ability-audio-ref-0.2.0`)
mapped by the ability's display name to the tray slot
(`lineup.abilities_for`), less:

* movement and footstep folders (`Mvmnt`, `Movement`, `FS_*`), no cast;
* rows the manifest leaves unmapped, unless the player's belief (BELIEF) or
  dev evidence (EVIDENCE) names their ability. The player's answers
  (PLAYER_MAPS) override the manifest's mapping for the files they name,
  once dev casts do not refute them (PLAYER_MAPS_NOT_APPLIED);
* shared files: a file whose sound event the ability montages of two or
  more abilities play (`ability_audio.shared_reference_mask`, over the
  montage export MONTAGES). On build `release-13.06-shipping-18-5590001`
  only Sova's Shock Bolt and Recon Bolt equips share events
  [domain:abilities/sova-bolt-equips-share-sounds].

A release event two abilities play (PHASE_GROUPS) is neither's: its files
are the phase group's own class, and the witness names the slot from the
group's landing files after the release (`ability_audio.cast_verdicts`).
The fit stores each group's landing files and, per member, the landing
track's level at one false fire per live minute on dev; thresholds are per
kit-level class, a group's family as one.

It replaces the split, the reference rule and the fit that lived in
`prototypes/ability_audio_eval.py` (`ability-audio-params-0.1.1`); that
script now passes this command the probe's inputs.

`--eval` scores the dev and held sessions of the set's split, the
player-verified casts (`labels/tray_object`) inside them, and the demos
(`labels/demo_cast_class`) with stored log-mel, and judges the margin's
calibration to P(right) on held casts and demos (`calibrate_margin`): the
set's stored calibration where it carries one, else one fitted on dev.

`--calibrate` derives the current set from CALIBRATED_FROM: the same
arrays, and per agent the margin calibration `ability_audio.calibrate`
fits on that set's dev casts (`ability-audio-params-0.2.2`), which the
witness reads to give each cast's `p_right` beside its margin.

`--late-phase` derives the current set from LATE_FROM: the same arrays,
thresholds and calibration, and each phase group's late templates (from the
gap export, LATE_MANIFEST) with their levels on dev
(`ability-audio-params-0.2.7`: the Recon Bolt's scan pulse).
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .ability_timeline import TRAY_OBJECT_CORRECTIONS_DIR, TRAY_OBJECT_DIR

#: The reference table and its version, under the store root.
REF_DIR = Path("reference") / "game-files" / "audio"
MANIFEST = REF_DIR / "manifest-0.2.0.jsonl"
REF_VERSION = "ability-audio-ref-0.2.0"
#: The ability montages exported from the game, under the store root.
MONTAGE_BUILD = "release-13.06-shipping-18-5590001"
MONTAGES = (Path("reference") / "game-files" / MONTAGE_BUILD / "ability-anims"
            / "manifest-montages.jsonl")
#: The player's verified casts and the demos' cast census, under the store root.
VERIFIED_DIR = TRAY_OBJECT_DIR
DEMO_DIR = Path("labels") / "demo_cast_class"
#: Folders whose files are movement, not a cast.
MOVEMENT = ("Mvmnt", "Movement")
#: The player's belief of 2026-10-03: Reyna's unmapped Abil_E folder is Dismiss.
BELIEF = {("Reyna", "Abil_E"): ("Dismiss", "player_belief_20261003")}
#: Unmapped rows mapped on evidence (2026-10-03): (agent, folder, file-name
#: prefixes, ability, basis). The name's token says the ability, and on dev
#: sessions alone the files fire only on that ability's casts.
EVIDENCE = [
    ("Skye", "Abil_E", ("Guide_Taz_", "Guide_AbilE_", "Guide_Abil_E_Attack"), "Trailblazer",
     "player_20261003+name_token_taz+dev_cooccurrence_20261003"),
    ("Sova", "Abil_X", ("Hunter_S0_AB_X_SuperBolt_OnBeam_",), "Hunter's Fury",
     "name_token_onbeam+dev_cooccurrence_20261003"),
]
#: The player's answers, each overriding the manifest's mapping for the named
#: files only: (agent, file-name prefixes, ability, basis)
#: [domain:abilities/sova-abilq-cast-is-shock-bolt]. Skye's ScoutExpire map
#: to Guiding Light (0.2.1, 0.2.2) is superseded
#: [domain:abilities/skye-scout-expire-is-guiding-light]: see
#: `END_PHASE_LEFT_OUT`.
PLAYER_MAPS: list[tuple] = []
#: Files of an ability that play at its end, not at its cast, left out of the
#: cast-window references: (agent, file-name prefixes, ability, basis, why).
#: Skye's ScoutExpire is Trailblazer's, played when the scout ends
#: [domain:abilities/skye-scout-expire-is-trailblazer]. On 2026-10-04 it won
#: no dev cast as Trailblazer (Skye dev top-1 67/70 mapped or left out), and
#: the pre-registered rule left it out on that tie.
END_PHASE_LEFT_OUT = [
    ("Skye", ("Guide_AbilE_ScoutExpire_3P",), "Trailblazer",
     "player_20261004+gamedata_ability-states-0.2.0",
     "plays at Pawn_Guide_Q_PossessableScout ReceiveEndPlay (phase end), not at the cast"),
]
#: Player answers recorded but not applied, with the dev measurement that
#: refused them. Remapping Sova's Hunter_AbilQ_Cast_* to Shock Bolt dropped
#: Sova dev top-1 86/98 -> 68/98; leaving them out, 86 -> 85, below the
#: pre-registered bar. From `ability-audio-params-0.2.5` the files are
#: neither bolt's: they are the bolts' shared release (PHASE_GROUPS).
PLAYER_MAPS_NOT_APPLIED = [
    ("Sova", ("Hunter_AbilQ_Cast_",), "Shock Bolt", "player_belief_20261004",
     "dev top-1 86/98 -> 68/98 remapped, 85/98 left out; superseded by the shared "
     "release (PHASE_GROUPS, ability-audio-params-0.2.5)"),
]
#: Phase groups: abilities whose casts share a sound, told apart by a later
#: phase. The files of a release event become the group's own class (its
#: name); at the kit level the group's members and that class score as one
#: family; where the family wins, the slot is the member whose landing files
#: score higher from `post_s[0]` to `post_s[1]` s after the release
#: (`ability_audio.cast_verdicts`). Each member's landing level is its
#: landing track's level at one false fire per live minute on dev. Sova's
#: bolts share Play_Hunter_AbilQ_Cast
#: [domain:abilities/sova-bolts-share-release-sound]; Shock Bolt lands with
#: Play_Hunter_AbilGrenade_Hit_3P [domain:abilities/sova-shock-bolt-landing-sound],
#: Recon Bolt flies with Play_Hunter_AbilQ_Missile_3P_upd and lands with
#: Play_Hunter_AbilQ_Hit_3P_upd [domain:abilities/sova-recon-bolt-landing-sound].
#: The landing sets (by event) and the window 0.05 to 2.0 s were chosen on
#: Sova dev casts alone by the rule pre-registered as
#: sova-bolt-phases-20261004 (dev top-1, then fewer bolt_unknown, then the
#: shorter window): every end from 2.0 to 3.0 s tied on dev.
#: A member's late phase (`late_events`, scored from `late_post_s[0]` to
#: `late_post_s[1]` s after the release) names a bolt no landing names. The
#: Recon Bolt's scan pulse, Play_Hunter_Abil_SonarBolt_SonarPing_upd, is
#: louder than its landing, which the caster hears only within his audio
#: range [domain:abilities/sova-recon-bolt-pulse-louder]
#: [domain:abilities/sova-recon-bolt-landing-audible-range]; its media is in
#: the gap export (LATE_MANIFEST), not the reference table. The window and
#: the level rule were fixed before scoring (recon-recovery-20261004). A
#: pulse not heard names nothing: whether it carries at every distance is
#: unsettled [domain:abilities/sova-recon-bolt-pulse-audible-range]. The
#: Recon Bolt's minimap ring, drawn for everyone
#: [domain:abilities/sova-recon-bolt-minimap-everyone], is another channel's
#: witness and is not taken here.
PHASE_GROUPS = [
    {"agent": "Sova", "name": "Q+E", "abilities": ("Shock Bolt", "Recon Bolt"),
     "release_events": ("Play_Hunter_AbilQ_Cast",),
     "landing_events": {"Shock Bolt": ("Play_Hunter_AbilGrenade_Hit_3P",),
                        "Recon Bolt": ("Play_Hunter_AbilQ_Hit_3P_upd",
                                       "Play_Hunter_AbilQ_Missile_3P_upd")},
     "post_s": (0.05, 2.0),
     "late_events": {"Recon Bolt": ("Play_Hunter_Abil_SonarBolt_SonarPing_upd",)},
     "late_post_s": (0.05, 6.0),
     "basis": "census_demo-audio-census-20261004+gamedata_ability-states-0.2.0+player_20261004"},
]
#: The game's sound files the reference table lacks (`audio-sfx-gaps-0.1.0`,
#: build release-13.06-shipping-18-5590001), under the store root; the late
#: phases' files come from here.
LATE_DIR = Path("reference") / "game-files" / "audio-sfx-gaps-0.1.0"
LATE_MANIFEST = LATE_DIR / "manifest.jsonl"
#: The set `--late-phase` derives the current set from: its arrays, with each
#: phase group's late templates and levels added.
LATE_FROM = "ability-audio-params-0.2.6"
#: Corrections the player made to a verified label, stored beside the labels,
#: never over them; `ability_timeline.tray_object_labels` applies them.
CORRECTIONS_DIR = TRAY_OBJECT_CORRECTIONS_DIR
#: The set `--calibrate` derives the current set from: the same arrays, with
#: the margin calibration fitted on its dev casts.
CALIBRATED_FROM = "ability-audio-params-0.2.5"
#: The P(right) at which a verdict counts as accepted in the report.
ACCEPT_P = 0.95


def sid_of(name: str) -> str:
    return name.split(":")[0]


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def montage_plays(store_root) -> dict[str, set]:
    """{"<codename>|<event>": the abilities whose montages play it}, from the
    montage export: an ability is the montage's `_S0_<token>_` (a slot
    token) or else its `Ability_<folder>`."""
    root = Path(store_root)
    base = (root / MONTAGES).parent
    plays: dict[str, set] = {}
    for line in (root / MONTAGES).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        m = re.match(r"ShooterGame/Content/Characters/([^/]+)/S0/Ability_([^/]+)/", r["game_path"])
        if not m or not r.get("output"):
            continue
        t = re.search(r"_S0_([A-Za-z0-9]+)_", r["game_path"].split("/")[-1])
        tok = t.group(1) if t and len(t.group(1)) <= 2 else m.group(2)
        text = (base / r["output"]).read_text(encoding="utf-8")
        for ev in set(re.findall(r"(Play_[A-Za-z0-9_]+)", text)):
            plays.setdefault(f"{m.group(1)}|{ev}", set()).add(tok)
    return plays


def references(store_root, agent: str, plays: dict[str, set]) -> tuple[list[dict], dict]:
    """The agent's reference rows with their class (a tray slot), and what
    the rule kept and left out."""
    from .adjudication.ability_audio import shared_reference_mask
    from .lineup import abilities_for
    root = Path(store_root)
    kit = abilities_for(agent, str(root))
    slot_of = {v: k for k, v in kit.items()}
    out, why = [], Counter()
    for line in (root / MANIFEST).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("agent") != agent:
            continue
        parts = (r.get("folder") or "").split("/")
        if parts[0] in MOVEMENT or any(p.startswith("FS_") for p in parts):
            why["movement_left_out"] += 1
            continue
        ability, basis = r.get("ability"), r.get("map_basis")
        name = r["flac"].split("/")[-1]
        if any(e[0] == agent and name.startswith(e[1]) for e in END_PHASE_LEFT_OUT):
            why["end_phase_left_out"] += 1
            continue
        evs = {e.split("/")[-1] for e in (r.get("events") or [])}
        grp = next((g for g in PHASE_GROUPS if g["agent"] == agent
                    and evs & set(g["release_events"])), None)
        if grp:
            # A release two abilities share: the group's own class.
            out.append({"flac": r["flac"], "class": grp["name"],
                        "ability": " / ".join(grp["abilities"]),
                        "basis": f"{grp['basis']} (manifest: {ability} by {basis})",
                        "events": [f"{r.get('codename')}|{e}" for e in sorted(evs)]})
            continue
        pm = next((p for p in PLAYER_MAPS if p[0] == agent and name.startswith(p[1])), None)
        if pm:
            # The player's answer overrides the manifest's mapping; the row
            # keeps what the manifest said.
            ability, basis = pm[2], f"{pm[3]} (manifest: {ability} by {basis})"
        if ability is None:
            belief = next((v for (a, f), v in BELIEF.items() if a == agent and f in parts), None)
            if belief:
                ability, basis = belief
        if ability is None:
            name = r["flac"].split("/")[-1]
            hit = next((e for e in EVIDENCE if e[0] == agent and e[1] in parts
                        and name.startswith(e[2])), None)
            if hit:
                ability, basis = hit[3], hit[4]
        if ability is None:
            why["unmapped_left_out"] += 1
            continue
        cls = slot_of.get(ability)
        if cls is None:
            why[f"not_in_kit:{ability}"] += 1
            continue
        out.append({"flac": r["flac"], "class": cls, "ability": ability, "basis": basis,
                    "events": [f"{r.get('codename')}|{e.split('/')[-1]}"
                               for e in (r.get("events") or [])]})
    keep = shared_reference_mask([o["events"] for o in out], plays)
    shared = [o["flac"] for o, k in zip(out, keep) if not k]
    out = [o for o, k in zip(out, keep) if k]
    why["shared_left_out"] += len(shared)
    for o in out:
        why[f"{o['class']}:{o['basis']}"] += 1
    return out, {"kit": kit, "counts": dict(sorted(why.items())), "shared_files": shared,
                 "slots_without_reference": sorted(set(kit) - {o["class"] for o in out})}


def phase_groups(agent: str, refs: list[dict], kit: dict) -> list[dict]:
    """The agent's PHASE_GROUPS as the witness reads them: the member slots,
    the group's class (its name), each member's landing files (the kept
    references whose events include the member's landing events) and the
    post-release window. The levels are the fit's."""
    slot_of = {v: k for k, v in kit.items()}
    out = []
    for g in PHASE_GROUPS:
        if g["agent"] != agent or not all(a in slot_of for a in g["abilities"]):
            continue
        landing = {}
        for ab in g["abilities"]:
            evs = set(g["landing_events"].get(ab, ()))
            landing[slot_of[ab]] = [r["flac"] for r in refs if r["class"] == slot_of[ab]
                                    and evs & {e.split("|")[-1] for e in r["events"]}]
        out.append({"name": g["name"], "members": [slot_of[a] for a in g["abilities"]],
                    "abilities": list(g["abilities"]), "release_events": list(g["release_events"]),
                    "landing_events": {slot_of[a]: list(v) for a, v in g["landing_events"].items()},
                    "landing": landing, "post_s": list(g["post_s"]), "basis": g["basis"]})
        if g.get("late_events"):
            out[-1].update(late_events={slot_of[a]: list(v) for a, v in g["late_events"].items()},
                           late_post_s=list(g["late_post_s"]))
    return out


def late_references(store_root, agent: str, groups: list[dict]) -> list[dict]:
    """The late-phase files of the agent's phase groups: the gap export's
    rows (LATE_MANIFEST) whose events a member's `late_events` name, each
    with its class LATE + slot, so it scores in no kit class. `flac` is the
    path under the store root."""
    from .adjudication.ability_audio import LATE
    want = {e: s for g in groups for s, evs in (g.get("late_events") or {}).items() for e in evs}
    if not want:
        return []
    out = []
    for line in (Path(store_root) / LATE_MANIFEST).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("agent") != agent:
            continue
        for e in r.get("events") or ():
            if e in want:
                out.append({"flac": (LATE_DIR / r["flac"]).as_posix(), "class": f"{LATE}{want[e]}",
                            "ability": f"late:{e}", "basis": f"{r.get('ref_version')}|{e}"})
    return out


def _late_templates(store_root, agent: str, groups: list[dict], P, ar):
    """(whitened late templates, their classes, their file rows), and each
    group's `late` {slot: files}, set in place."""
    from .adjudication import ability_audio as aa
    temps, labels, files = [], [], []
    for r in late_references(store_root, agent, groups):
        T = aa.template(aa.reference_logmel(Path(store_root) / r["flac"]))
        if T is None:
            continue
        temps.append(aa.whiten_template(T, P, ar))
        labels.append(r["class"])
        files.append({"flac": r["flac"], "ability": r["ability"], "basis": r["basis"]})
    for g in groups:
        if g.get("late_events"):
            g["late"] = {s: [f["flac"] for f, c in zip(files, labels) if c == f"{aa.LATE}{s}"]
                         for s in g["late_events"]}
    return temps, labels, files


def _late_levels(groups: list[dict], peaks: dict, live_min: float) -> None:
    """Each group's `late_levels`: a member's late track's level at one
    false fire per live minute on dev, set in place."""
    from .adjudication import ability_audio as aa
    for g in groups:
        if g.get("late"):
            g["late_levels"] = {s: aa.threshold_at(peaks[f"{aa.LATE}{s}"], live_min)
                                for s, fl in g["late"].items() if fl}


# ---------------------------------------------------------------------------
# The gate, once
# ---------------------------------------------------------------------------

def gate_snapshot(store, sids: list[str], supplied: dict[str, str]) -> dict:
    """Per session the gate's rows, the player's agent and its basis, the
    kit spans and the stamps read."""
    from .ability_timeline import player_tray_casts, stored_gate_inputs
    from .adjudication.ability_state import player_agent_verdict
    from .adjudication.ult_cast import DROP_FIELDS
    from .lineup import load_lineup
    res = {}
    for sid in sids:
        man = store.read_manifest(sid)
        date = man["ingested_at"][:10]   # the store's session date (cli._date_of)
        stored = store.read_events("tray_drop", sid)
        cov = next((r for r in stored if r.get("kind") == "coverage"), {})
        drops = [{k: r[k] for k in DROP_FIELDS if k in r} for r in stored
                 if r.get("kind") == "drop"]
        rounds = store.read_rounds(sid, date).to_pylist()
        verdict = player_agent_verdict(load_lineup(sid, store.root), sid)
        who, why = verdict["agent"], "identity arbiter"
        if who is None and sid in supplied:
            who, why = supplied[sid], f"supplied on the command line; the arbiter names none " \
                                      f"({verdict.get('status')})"
        if who is None:
            print(f"{sid}: the arbiter names no agent -- left out")
            continue
        gate, stamps = stored_gate_inputs(store, sid, date, rounds, who)
        rows = player_tray_casts(drops, rounds=rounds, **gate)
        res[sid] = {"agent": who, "agent_basis": why, "arbiter_agent": verdict["agent"],
                    "path": man["source"].get("path"),
                    "stamps": {**stamps, "tray_drop": cov.get("tray_version")},
                    "kit_spans": gate["kit_spans"],
                    "rows": [{"t_ms": r["t_ms"], "slot": r["slot"],
                              "player_cast": r["player_cast"], "reason": r["reason"]}
                             for r in rows]}
        print(sid, who, "drops", len(rows), "casts", sum(r["player_cast"] for r in rows),
              flush=True)
    return res


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def audio_paths(store_root, sid: str, audio_dirs) -> dict:
    """The log-mel and labels of a session: the store's, else the first
    `audio_dirs` entry holding them; {} where the store has both. A store
    holding the log-mel without the labels does not count: the pair comes
    from one place."""
    from .ability_timeline import AUDIO_GATE_DIR
    gate_dir = Path(store_root) / AUDIO_GATE_DIR
    if ((gate_dir / "features" / f"{sid}.npz").is_file()
            and (gate_dir / "labels" / f"{sid}.json").is_file()):
        return {}
    for d in audio_dirs or ():
        fp = Path(d) / "features" / f"{sid}.npz"
        if fp.is_file():
            return {"features_path": fp, "labels_path": Path(d) / "labels" / f"{sid}.json"}
    return {}


def verified_casts(store_root) -> dict[str, list[dict]]:
    """{session: the player's verified casts}: time and slot, read through
    `ability_timeline.tray_object_labels`, so a corrected label carries its
    correction's slot, and `label_slot` the original."""
    from .ability_timeline import tray_object_labels
    out: dict[str, list[dict]] = {}
    for f in sorted((Path(store_root) / VERIFIED_DIR).glob("*.jsonl")):
        for r in tray_object_labels(store_root, f.stem)[0]:
            row = {"t_ms": float(r["t_drop_s"]) * 1000.0, "slot": r["slot"], "key": r["key"]}
            if r["value_source"] == "player_correction":
                row.update(label_slot=r["label_slot"], correction=r["correction"]["basis"])
            out.setdefault(r["session_id"], []).append(row)
    return out


def match_session(store_root, name: str, gate: dict, audio_dirs=(), verified=None):
    """(the stored audio of a match session or half, None) or (None, why)."""
    from .ability_timeline import audio_session
    from .adjudication.ability_audio import FPS
    sid = sid_of(name)
    g = gate[sid]
    where = audio_paths(store_root, sid, audio_dirs)
    if ":" in name:
        from .ability_timeline import AUDIO_GATE_DIR
        fp = where.get("features_path") or (Path(store_root) / AUDIO_GATE_DIR / "features"
                                            / f"{sid}.npz")
        with np.load(fp, allow_pickle=True) as z:
            n = len(z["ok"])
        mid = n / (2 * FPS)
        where["span_s"] = (0.0, mid) if name.endswith(":first") else (mid, n / FPS)
    s, why = audio_session(store_root, sid, g["rows"], g["agent"], g["kit_spans"],
                           features_path=where.get("features_path"),
                           labels_path=where.get("labels_path"), span_s=where.get("span_s"))
    if s is None:
        return None, why
    lo, hi = where.get("span_s") or (0.0, np.inf)
    s["span_s"] = where.get("span_s")
    s["verified"] = [dict(v, frame=int(v["t_ms"] / 1000.0 * FPS))
                     for v in (verified or {}).get(sid, []) if lo <= v["t_ms"] / 1000.0 < hi]
    return s, None


def demo_truth(store_root, sid: str) -> list[dict]:
    """A demo's census casts, one per key."""
    rows, seen = [], set()
    p = Path(store_root) / DEMO_DIR / f"{sid}.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["key"] not in seen:
                seen.add(r["key"])
                rows.append({"t_ms": float(r["t_ms"]), "slot": r["slot"], "key": r["key"],
                             "agent": r["agent"]})
    return rows


def demo_census_sessions(store_root, audio_dirs=()) -> dict[str, str]:
    """{demo session: its agent} for every demo census with stored log-mel."""
    from .ability_timeline import AUDIO_GATE_DIR
    out = {}
    for p in sorted((Path(store_root) / DEMO_DIR).glob("*.jsonl")):
        sid = p.stem
        has = ((Path(store_root) / AUDIO_GATE_DIR / "features" / f"{sid}.npz").is_file()
               or any((Path(d) / "features" / f"{sid}.npz").is_file() for d in audio_dirs or ()))
        truth = demo_truth(store_root, sid)
        if has and truth:
            out[sid] = truth[0]["agent"]
    return out


def demo_session(store_root, sid: str, audio_dirs=()):
    """A demo's stored audio: every frame with audio is live; the null
    frames are live and unexplained by a drop or a census cast; the casts
    are the census's; every tray drop bounds a cast's window."""
    from .ability_timeline import AUDIO_GATE_DIR, features_stamp
    from .adjudication.ability_audio import FPS, explained, session_frames
    root = Path(store_root)
    fp = root / AUDIO_GATE_DIR / "features" / f"{sid}.npz"
    if not fp.is_file():
        fp = audio_paths(root, sid, audio_dirs).get("features_path")
    z = np.load(fp, allow_pickle=True)
    med = z["med"] if "med" in z.files else np.median(z["L"].astype(np.float32), axis=0)
    X = session_frames(z["L"], med)
    n = len(X)
    live = z["ok"][:n].astype(bool)
    drops = [r for r in (json.loads(x) for x in (root / "events" / "tray_drop" / f"{sid}.jsonl")
                         .read_text(encoding="utf-8").splitlines() if x.strip())
             if r.get("kind") == "drop"]
    truth = demo_truth(root, sid)
    code = explained(n, [d["t_ms"] / 1000.0 for d in drops] + [t["t_ms"] / 1000.0 for t in truth],
                     [], [])
    return {"X": X, "live": live, "code": code, "bg": live & (code == 3),
            "casts": [{"t_ms": t["t_ms"], "slot": t["slot"], "frame": int(t["t_ms"] / 1000.0 * FPS)}
                      for t in truth],
            "neighbours": np.array([int(d["t_ms"] / 1000.0 * FPS) for d in drops], int),
            "verified": [], "live_min": float(live.sum()) / (60.0 * FPS),
            "stamps": {"audio_features": features_stamp(z, fp), "features_path": Path(fp).as_posix(),
                       "tray_drop": "events/tray_drop"}}


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------

def fit_params(store_root, out_root, gate: dict, audio_dirs=(), agents=None, xp=np) -> Path:
    """Fit and save a parameter set (`ABILITY_AUDIO_PARAMS_VERSION`) under
    `out_root`: one whitener over every dev session, each agent's
    references whitened by it, and each class's threshold over every dev
    session. `agents` defaults to the gate's agents and the demos'."""
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    root = Path(store_root)
    split = aa.split_sessions(_sessions_by_agent(gate))
    dev = sorted(n for sp in split.values() for n in sp["dev"])
    agents = sorted(agents or set(split) | set(demo_census_sessions(root, audio_dirs).values()))

    def dev_sessions():
        for n in dev:
            s, why = match_session(root, n, gate, audio_dirs)
            if s is None:
                raise SystemExit(f"{n}: {why}")
            yield n, s

    t0 = time.time()
    stamps = {}

    def pairs():
        for n, s in dev_sessions():
            stamps[n] = {**gate[sid_of(n)]["stamps"], **s["stamps"]}
            yield s["X"], s["bg"]

    W = aa.fit_whitener(pairs())
    print(f"whitener: {len(dev)} dev sessions, {W['bg_frames']} null frames, cond "
          f"{W['cond']:.0f}, AR {np.round(W['ar'], 4)} ({time.time() - t0:.0f} s)", flush=True)
    plays = montage_plays(root)
    per = {}
    for agent in agents:
        refs, rule = references(root, agent, plays)
        temps, labels, files = [], [], []
        for r in refs:
            T = aa.template(aa.reference_logmel(root / REF_DIR / r["flac"]))
            if T is None:
                continue
            temps.append(aa.whiten_template(T, W["P"], W["ar"]))
            labels.append(r["class"])
            files.append({"flac": r["flac"], "ability": r["ability"], "basis": r["basis"]})
        kept = {f["flac"] for f in files}
        groups = phase_groups(agent, [r for r in refs if r["flac"] in kept], rule["kit"])
        lt, ll, lf = _late_templates(root, agent, groups, W["P"], W["ar"])
        temps, labels, files = temps + lt, labels + ll, files + lf
        per[agent] = {"temps": temps, "labels": labels, "files": files, "rule": rule,
                      "groups": groups, "peaks": {}}
        print(f"{agent}: {len(temps)} templates {dict(Counter(labels))}, "
              f"shared left out {len(rule['shared_files'])}"
              + "".join(f", group {g['name']} landing "
                        f"{ {s: len(v) for s, v in g['landing'].items()} }" for g in groups),
              flush=True)
    live_min = 0.0
    for n, s in dev_sessions():
        t1 = time.time()
        Xw = aa.whiten_frames(s["X"], W["mu"], W["P"], W["ar"])
        for agent, a in per.items():
            if not a["temps"]:
                continue
            # Thresholds of the kit-level classes (a phase group's family as
            # one) and levels of the landing tracks.
            tr = aa.session_tracks(Xw, {"templates": a["temps"], "labels": a["labels"],
                                        "files": a["files"], "groups": a["groups"]}, s["bg"], xp)
            kt = aa.kit_view(tr, a["groups"])
            kt.update({k: v for k, v in tr.items() if k.startswith(aa.PHASE_TRACKS)})
            for c, v in kt.items():
                a["peaks"].setdefault(c, []).append(aa.false_fire_peaks(v, s["live"], s["code"]))
        live_min += s["live_min"]
        print(f"  thresholds: {n} ({time.time() - t1:.0f} s)", flush=True)
    agents_out = {}
    for agent, a in per.items():
        if not a["temps"]:
            print(f"{agent}: no references -- no parameters")
            continue
        thr = {c: aa.threshold_at(v, live_min) for c, v in a["peaks"].items()
               if c != aa.NONE and not c.startswith(aa.PHASE_TRACKS)}
        for g in a["groups"]:
            g["levels"] = {m: aa.threshold_at(a["peaks"][f"{aa.LANDING}{m}"], live_min)
                           for m in g["members"]}
            print(f"{agent}: group {g['name']} landing levels "
                  f"{ {k: round(v, 3) for k, v in g['levels'].items()} }", flush=True)
        _late_levels(a["groups"], a["peaks"], live_min)
        agents_out[agent] = {
            "mu": W["mu"], "P": W["P"], "ar": W["ar"], "templates": a["temps"],
            "labels": a["labels"], "files": a["files"], "slots": a["rule"]["kit"],
            "thresholds": thr, "groups": a["groups"],
            "dev": [{"name": n, "path": gate[sid_of(n)]["path"], "stamps": stamps.get(n),
                     "agent": gate[sid_of(n)]["agent"],
                     "agent_basis": gate[sid_of(n)]["agent_basis"]} for n in dev],
            "fit": {"whitener": "pooled", "bg_frames": W["bg_frames"],
                    "band_condition": round(W["cond"], 1),
                    "ar2": [round(float(x), 5) for x in W["ar"]], "live_min": round(live_min, 2),
                    "templates": len(a["temps"]), "by_class": dict(Counter(a["labels"])),
                    "reference_rule_counts": a["rule"]["counts"],
                    "shared_files": a["rule"]["shared_files"],
                    "slots_without_reference": a["rule"]["slots_without_reference"],
                    "own_dev_sessions": split.get(agent, {}).get("dev", [])}}
        print(f"{agent}: thresholds { {k: round(v, 3) for k, v in thr.items()} }", flush=True)
    prov = {"ability_audio_version": ABILITY_AUDIO_VERSION,
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fitted_by": "reticle ability-audio-fit --fit",
            "reference": {"manifest": MANIFEST.as_posix(), "ref_version": REF_VERSION,
                          "rule": "by the ability's display name to the tray slot "
                                  "(lineup.abilities_for), the player's maps overriding the "
                                  "manifest for the files they name; movement and footstep "
                                  "folders left out; files that play at an ability's end "
                                  "left out (end_phase_left_out); a release event two "
                                  "abilities share is its phase group's class "
                                  "(phase_groups); unmapped rows left out "
                                  "unless a belief or an evidence map names them",
                          "shared_rule": "a file whose sound event the ability montages of two "
                                         "or more abilities play is left out "
                                         "(ability_audio.shared_reference_mask)",
                          "montages": {"manifest": MONTAGES.as_posix(), "build": MONTAGE_BUILD},
                          "beliefs": [{"agent": a, "folder": f, "ability": v[0], "basis": v[1]}
                                      for (a, f), v in BELIEF.items()],
                          "player_maps": [{"agent": a, "prefixes": list(pre), "ability": ab,
                                           "basis": b} for a, pre, ab, b in PLAYER_MAPS],
                          "player_maps_not_applied": [
                              {"agent": a, "prefixes": list(pre), "ability": ab, "basis": b,
                               "refused_by": why} for a, pre, ab, b, why in PLAYER_MAPS_NOT_APPLIED],
                          "end_phase_left_out": [
                              {"agent": a, "prefixes": list(pre), "ability": ab, "basis": b,
                               "why": why} for a, pre, ab, b, why in END_PHASE_LEFT_OUT],
                          "evidence_maps": [{"agent": e[0], "folder": e[1], "prefixes": list(e[2]),
                                             "ability": e[3], "basis": e[4]} for e in EVIDENCE],
                          "phase_groups": [{**g, "abilities": list(g["abilities"]),
                                            "release_events": list(g["release_events"]),
                                            "landing_events": {k: list(v) for k, v
                                                               in g["landing_events"].items()},
                                            "post_s": list(g["post_s"])} for g in PHASE_GROUPS]},
            "split": split,
            "split_basis": "ability_audio.split_sessions: per agent the sessions sorted by id, "
                           "even positions dev, odd held; one session split at its frame "
                           "midpoint; demos always held",
            "whitening": {"pooled_over": dev, "shrink": aa.SHRINK, "eig_floor": aa.EIG_FLOOR,
                          "ar_min_run": aa.AR_MIN_RUN, "bands_hz": [aa.BAND_LO, aa.BAND_HI]},
            "template_rule": {"active_db": aa.ACTIVE_DB, "floor_db": aa.TEMPLATE_DB,
                              "max_s": aa.MAX_TEMPLATE_S},
            "candidate_rule": "the player's kit slots with references",
            "threshold_rule": f"{aa.THRESHOLD_FF_PER_MIN} false fire per live minute over every "
                              f"dev session's unexplained live frames, peaks {aa.PEAK_GAP} "
                              f"frames apart; per kit-level class (a phase group's family "
                              f"as one, ability_audio.kit_view), and per phase group member's "
                              f"landing track (the group's levels)",
            "gate": {sid: {"agent": g["agent"], "agent_basis": g["agent_basis"]}
                     for sid, g in gate.items()}}
    d = aa.save_params(out_root, ABILITY_AUDIO_PARAMS_VERSION, agents_out, prov)
    print("params ->", d)
    return d


def _sessions_by_agent(gate: dict) -> dict[str, list[str]]:
    by: dict[str, list[str]] = {}
    for sid, g in gate.items():
        by.setdefault(g["agent"], []).append(sid)
    return by


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def reliability_bins(p: np.ndarray, y: np.ndarray, bins=(0, .5, .8, .9, .95, .99, 1.0001)):
    """(expected calibration error, [[lo, hi, n, mean P, share right]])."""
    e, rel = 0.0, []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.any():
            e += m.sum() * abs(p[m].mean() - y[m].mean())
            rel.append([lo, round(hi, 2), int(m.sum()), round(float(p[m].mean()), 3),
                        round(float(y[m].mean()), 3)])
    return e / max(len(p), 1), rel


def _xy(rows):
    """(margins, 1 where the best referenced class was the slot) of the
    referenced rows that name a slot (a `bolt_unknown` names none)."""
    rows = [r for r in rows if r["referenced"] and r["best_ref"] is not None
            and np.isfinite(r["margin_ref"])]
    return (np.array([r["margin_ref"] for r in rows], float),
            np.array([r["best_ref"] == r["slot"] for r in rows], float))


def dev_calibration(rows_by_agent: dict[str, list[dict]], agents=None) -> dict:
    """`ability_audio.calibrate` over the dev casts of `rows_by_agent`, for
    `agents` (default: the rows' agents)."""
    from .adjudication.ability_audio import calibrate
    dev = {a: _xy([r for r in rows if r["kind"] == "dev"]) for a, rows in rows_by_agent.items()}
    return calibrate(dev, agents or list(rows_by_agent))


def calibrate_margin(rows_by_agent: dict[str, list[dict]], stored: dict | None = None) -> dict:
    """Margin (best referenced class over the runner-up) -> P(right),
    judged on held casts and demos. `stored` is the calibration the
    parameter set carries ({"pooled", "agents"}, `ability_audio.calibrate`);
    without it the calibration is fitted here on the rows' dev casts. The
    LLR is logit(P) less the logit of the pooled dev accuracy (natural log)."""
    from .adjudication.ability_audio import p_right
    cal = stored or dev_calibration(rows_by_agent)
    pooled = cal["pooled"]
    prior = pooled["dev_right"] / max(pooled["dev_n"], 1)
    out = {"source": "stored" if stored else "fitted_on_dev",
           "pooled": {"w": np.round(pooled["w"], 3).tolist(), "dev_n": pooled["dev_n"],
                      "dev_right": pooled["dev_right"]}}
    allp, ally = [], []
    for a, rows in rows_by_agent.items():
        c = cal["agents"].get(a) or {"w": pooled["w"], "basis": "pooled"}
        w = np.asarray(c["w"], float)
        for k in ("held", "demo"):
            x, y = _xy([r for r in rows if r["kind"] == k])
            if not len(x):
                continue
            p = p_right(x, w)
            e, rel = reliability_bins(p, y)
            llr = np.log(p / (1 - p)) - np.log(prior / (1 - prior))
            acc = p >= ACCEPT_P
            out.setdefault(a, {})[k] = {
                "basis": c["basis"], "w": np.round(w, 3).tolist(),
                "n": int(len(y)), "ece": round(float(e), 3), "reliability": rel,
                f"accepted_p{int(ACCEPT_P * 100)}": f"{int(y[acc].sum())}/{int(acc.sum())}",
                "llr_median_right": (round(float(np.median(llr[y == 1])), 2)
                                     if (y == 1).any() else None),
                "llr_median_wrong": (round(float(np.median(llr[y == 0])), 2)
                                     if (y == 0).any() else None)}
            if k == "held":
                allp.append(p), ally.append(y)
    if allp:
        p, y = np.concatenate(allp), np.concatenate(ally)
        e, rel = reliability_bins(p, y)
        out["all_held"] = {"n": int(len(y)), "ece": round(float(e), 3), "reliability": rel,
                           f"accepted_p{int(ACCEPT_P * 100)}":
                               f"{int(y[p >= ACCEPT_P].sum())}/{int((p >= ACCEPT_P).sum())}"}
    return out


def _score_rows(kind, name, casts, tracks, neighbours, params):
    """Rows for `casts` scored on `tracks` by the witness's own rule
    (`ability_audio.cast_verdicts`): every kit class's score, the verdict,
    and the best referenced slot and its margin (a phase group's later
    phase where the group wins; None for a bolt neither landing names)."""
    from .adjudication.ability_audio import cast_verdicts, kit_classes, referenced_slots
    if not casts:
        return []
    groups = params.get("groups") or []
    ref = referenced_slots(kit_classes(list(tracks), groups), groups)
    ids = cast_verdicts(tracks, [c["frame"] for c in casts], neighbours, params)
    out = []
    for c, v in zip(casts, ids):
        out.append({"kind": kind, "name": name, "t_ms": c["t_ms"], "slot": c["slot"],
                    "referenced": c["slot"] in ref, "best_ref": v["best_ref"],
                    "margin_ref": (float("nan") if v["margin_ref"] is None
                                   else float(v["margin_ref"])),
                    "verdict": v["verdict"], "reason": v["reason"], "scores": v["scores"],
                    "phase": v["phase"]})
    return out


def evaluate_params(store_root, params_root, gate: dict, audio_dirs=(), agents=None, xp=np,
                    version: str | None = None) -> dict:
    """Score set `version`'s (default `ABILITY_AUDIO_PARAMS_VERSION`) dev
    and held sessions, their verified casts and the demos; per agent the
    argmax top-1 over referenced casts and the verdicts per kind, the
    misses, and the calibration: the set's stored one where it carries one,
    else one fitted on the dev casts here."""
    from .ability_timeline import audio_cast_witness
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION
    version = version or ABILITY_AUDIO_PARAMS_VERSION
    root = Path(store_root)
    verified = verified_casts(root)
    demos = demo_census_sessions(root, audio_dirs)
    prov = json.loads((aa.params_path(params_root, version)
                       / "provenance.json").read_text(encoding="utf-8"))
    split = prov["split"]
    agents = sorted(agents or prov["agents"])
    stored = ({"pooled": prov["calibration"]["pooled"],
               "agents": {a: m["calibration"] for a, m in prov["agents"].items()}}
              if prov.get("calibration") else None)
    rows_by_agent, out = {}, {}
    for agent in agents:
        params, why = aa.load_params(params_root, version, agent)
        if params is None:
            print(f"{agent}: {why}")
            continue
        rows = []
        sp = split.get(agent, {"dev": [], "held": []})
        for kind in ("dev", "held"):
            for name in sp[kind]:
                s, why = match_session(root, name, gate, audio_dirs, verified)
                if s is None:
                    print(f"{name}: {why}")
                    continue
                g = gate[sid_of(name)]
                res = audio_cast_witness(root, sid_of(name), g["rows"], g["agent"],
                                         g["kit_spans"], params=params, session=s, xp=xp)
                tracks = res["tracks"]
                rows += _score_rows(kind, name, s["casts"], tracks, s["neighbours"], params)
                rows += _score_rows(f"{kind}_verified", name, s["verified"], tracks,
                                    s["neighbours"], params)
        for sid, a in demos.items():
            if a != agent:
                continue
            s = demo_session(root, sid, audio_dirs)
            Xw = aa.whiten_frames(s["X"], params["mu"], params["P"], params["ar"])
            tracks = aa.session_tracks(Xw, params, s["bg"], xp)
            rows += _score_rows("demo", sid, s["casts"], tracks, s["neighbours"], params)
        rows_by_agent[agent] = rows
        summ = {}
        for kind in ("dev", "held", "dev_verified", "held_verified", "demo"):
            r = [x for x in rows if x["kind"] == kind and x["referenced"]]
            if not r:
                continue
            v = Counter("right" if x["verdict"] == x["slot"] else "wrong" if x["verdict"]
                        else "refused" for x in r)
            summ[kind] = {"top1": f"{sum(x['best_ref'] == x['slot'] for x in r)}/{len(r)}",
                          "right": v["right"], "wrong": v["wrong"], "refused": v["refused"],
                          "unreferenced": sum(x["kind"] == kind and not x["referenced"]
                                              for x in rows)}
        out[agent] = {"summary": summ, "split": sp,
                      "demos": sorted(s for s, a in demos.items() if a == agent),
                      "misses": [x for x in rows if x["kind"] in ("held", "held_verified", "demo")
                                 and x["referenced"] and x["best_ref"] != x["slot"]]}
        print(agent, json.dumps(summ), flush=True)
    cal = calibrate_margin(rows_by_agent, stored)
    print(f"calibration ({cal['source']}) all held", json.dumps(cal.get("all_held")), flush=True)
    return {"params": prov["version"], "agents": out, "calibration": cal,
            "rows": {a: r for a, r in rows_by_agent.items()}}


def calibrate_params(store_root, params_root, gate: dict, audio_dirs=(), xp=np,
                     src_version: str = CALIBRATED_FROM) -> Path:
    """Derive set `ABILITY_AUDIO_PARAMS_VERSION` under `params_root` from
    `src_version`: its arrays unchanged and, per agent, the margin
    calibration fitted on the source set's dev casts alone
    (`ability_audio.calibrate`); held casts and demos never enter it."""
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION
    prov = json.loads((aa.params_path(params_root, src_version) / "provenance.json")
                      .read_text(encoding="utf-8"))
    res = evaluate_params(store_root, params_root, gate, audio_dirs, None, xp, src_version)
    cal = dev_calibration(res["rows"], list(prov["agents"]))
    for a, c in cal["agents"].items():
        print(f"{a}: calibration {c['basis']} w {np.round(c['w'], 3).tolist()} "
              f"(dev {c['dev_right']}/{c['dev_n']})", flush=True)
    note = {"rule": "P(the best referenced class is the cast's slot) = 1 / (1 + exp(-(w0 + w1 "
                    "margin))), the margin the best referenced class's score over the "
                    "referenced runner-up's (ability_audio.ref_margin); fitted by "
                    "ability_audio.calibrate on the split's dev casts (the gate's player casts "
                    "on dev sessions, referenced slots): an agent's own fit with "
                    f"{aa.CALIB_MIN} right and {aa.CALIB_MIN} wrong dev casts, else the pooled "
                    f"fit; ridge {aa.CALIB_L2}",
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fitted_by": "reticle ability-audio-fit --calibrate",
            "gate": {sid: {"agent": g["agent"], "stamps": g["stamps"]} for sid, g in gate.items()},
            "held_check": res["calibration"].get("all_held")}
    d = aa.save_calibrated(params_root, src_version, ABILITY_AUDIO_PARAMS_VERSION, cal, note)
    print("params ->", d)
    return d


def late_phase_params(store_root, params_root, gate: dict, audio_dirs=(), xp=np,
                      src_version: str = LATE_FROM) -> Path:
    """Derive set `ABILITY_AUDIO_PARAMS_VERSION` under `params_root` from
    `src_version`: its arrays, thresholds and calibration unchanged and, per
    agent whose phase group declares late events (PHASE_GROUPS), the late
    templates whitened by the set's own whitener, and each late track's
    level at one false fire per live minute over the set's dev sessions'
    null frames, the rule of every other level. Held casts never enter it."""
    from .adjudication import ability_audio as aa
    from .version import ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION
    root = Path(store_root)
    prov = json.loads((aa.params_path(params_root, src_version) / "provenance.json")
                      .read_text(encoding="utf-8"))
    dev = sorted(n for sp in prov["split"].values() for n in sp["dev"])
    late_of = {(g["agent"], g["name"]): g for g in PHASE_GROUPS if g.get("late_events")}
    per = {}
    for agent in prov["agents"]:
        params, _ = aa.load_params(params_root, src_version, agent)
        groups = [dict(g) for g in params["groups"]]
        for g in groups:
            src = late_of.get((agent, g["name"]))
            if src:
                slot_of = dict(zip(g["abilities"], g["members"]))
                g.update(late_events={slot_of[a]: list(v) for a, v in src["late_events"].items()},
                         late_post_s=list(src["late_post_s"]))
        if not any(g.get("late_events") for g in groups):
            continue
        temps, labels, files = _late_templates(root, agent, groups, params["P"], params["ar"])
        per[agent] = {"params": params, "templates": temps, "labels": labels, "files": files,
                      "groups": groups, "peaks": {}}
        print(f"{agent}: late templates {dict(Counter(labels))}", flush=True)
    live_min = 0.0
    for n in dev:
        s, why = match_session(root, n, gate, audio_dirs)
        if s is None:
            raise SystemExit(f"{n}: {why}")
        for agent, a in per.items():
            p = a["params"]
            Xw = aa.whiten_frames(s["X"], p["mu"], p["P"], p["ar"])
            tr = aa.class_tracks(Xw, a["templates"], a["labels"], s["bg"], xp)
            for c, v in tr.items():
                a["peaks"].setdefault(c, []).append(aa.false_fire_peaks(v, s["live"], s["code"]))
        live_min += s["live_min"]
        print(f"  late levels: {n}", flush=True)
    added = {}
    for agent, a in per.items():
        _late_levels(a["groups"], a["peaks"], live_min)
        for g in a["groups"]:
            if g.get("late_levels"):
                print(f"{agent}: group {g['name']} late levels "
                      f"{ {k: round(v, 3) for k, v in g['late_levels'].items()} }", flush=True)
        added[agent] = {k: a[k] for k in ("templates", "labels", "files", "groups")}
    note = {"ability_audio_version": ABILITY_AUDIO_VERSION,
            "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fitted_by": "reticle ability-audio-fit --late-phase",
            "manifest": LATE_MANIFEST.as_posix(),
            "rule": "per phase group member with late events, the gap export's files of those "
                    "events as templates (class late:<slot>, in no kit class), whitened by the "
                    "source set's whitener; level at one false fire per live minute over the "
                    "source set's dev sessions' unexplained live null frames; a late phase "
                    "names a release no landing names (ability_audio.cast_verdicts)",
            "live_min": round(live_min, 2), "dev_sessions": dev,
            "phase_groups": [{**g, "abilities": list(g["abilities"]),
                              "late_events": {k: list(v) for k, v in g["late_events"].items()},
                              "late_post_s": list(g["late_post_s"])}
                             for g in PHASE_GROUPS if g.get("late_events")]}
    d = aa.save_with_templates(params_root, src_version, ABILITY_AUDIO_PARAMS_VERSION, added, note)
    print("params ->", d)
    return d


def main(args) -> int:
    """`reticle ability-audio-fit`."""
    import os

    from . import ult_lines
    from .store import Store
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)   # Below Normal
    from .ability_timeline import AUDIO_GATE_DIR
    store = Store(args.store)
    dirs = [Path(d) for d in args.audio_dir or ()]
    if args.gate:
        supplied = dict(s.split("=", 1) for s in args.supply or ())
        sids = sorted(p.stem for p in (store.root / AUDIO_GATE_DIR / "labels").glob("*.json"))
        sids += sorted({p.stem for d in dirs for p in (d / "labels").glob("*.json")} - set(sids))
        res = gate_snapshot(store, sids, supplied)
        Path(args.gate).write_text(json.dumps(res, indent=0), encoding="utf-8")
        print("gate ->", args.gate)
        return 0
    if not args.gate_in:
        print("--fit and --eval read a gate snapshot: pass --gate-in (made by --gate)")
        return 2
    gate = json.loads(Path(args.gate_in).read_text(encoding="utf-8"))
    xp = ult_lines.array_module()
    if args.fit:
        fit_params(store.root, Path(args.fit), gate, dirs, args.agent, xp)
    if getattr(args, "calibrate", None):
        calibrate_params(store.root, Path(args.calibrate), gate, dirs, xp)
    if getattr(args, "late_phase", None):
        late_phase_params(store.root, Path(args.late_phase), gate, dirs, xp)
    if args.eval:
        res = evaluate_params(store.root, Path(args.eval), gate, dirs, args.agent, xp)
        if args.json:
            Path(args.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0
