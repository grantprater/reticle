r"""Ability actors in VALORANT replays as external truth for evaluation.

Moved into the acceptance harness on 2026-10-09
(`reticle/harness/abilities.py`, task `harness-t1d-20261009`): the scorer's
constants and `actor_census`. This file imports them back.

    .\.venv\Scripts\python.exe prototypes\replay_abilities.py census MATCH [--record]
    .\.venv\Scripts\python.exe prototypes\replay_abilities.py score SESSION [--record]
    .\.venv\Scripts\python.exe prototypes\replay_abilities.py survey [--record]

What this is, and what it is not
--------------------------------
The sibling of `replay_truth.py`. Where that file scores players' positions,
this one reads what the replay holds of the abilities: every non-player actor
the server spawned (projectiles, placed game objects, pawns, ground patches,
ult orbs, the planted spike), with its class, spawn point, rotation, open and
close times and the `Owner`/`Instigator` references; and the server's cast
records (`AbilityCastsThisRound`) and ult state (`bUltimateActive`).

What replay data may fit is the use policy in
`docs/EXTERNAL_GROUND_TRUTH.md`. This module uses it
for evaluation only. Nothing in `reticle/` reads this file or its outputs.

How a class is mapped to an ability, from evidence for that ability
--------------------------------------------------------------------
Never by name keyword and never by analogy between abilities. A class maps to
an ability when all three hold:

1. its replicated class path lies in an ability folder,
   `/Game/Characters/<code>/S0/Ability_<L>/...`;
2. the extracted game files (`<store>/reference/game-files/<build>/
   ability-data`) hold a `UIData*` for that folder, whose display name names
   the ability; the folder letter is the game's, not the tray key
   [domain:abilities/minimap-textures-sova];
3. every instance's `Instigator` chain ends at a player pawn of class
   `<code>_PC_C`, and the replay's playerLoadouts name that player's agent.

A class failing any of the three stays unmapped, with the reason. A class
outside `/Game/Characters` (ult orbs, the spike) is named by its own path.

The cast records' `Slot` byte is not documented; `census` derives its meaning
per agent by pairing each cast with the first world actor of the same player
that opens after it, and reports the table rather than assuming it.

The three commands
------------------
`census` lists every non-player actor class of one parse with its counts,
fields and mapping, the cast records and the ult transitions.

`score` lives in the one harness since 2026-10-09
(`question_acceptance.py replay-abilities`, harness step 9), which joins
the `ability_shape` ring centres and dropped spike glyphs to every replay
entity; this command forwards to it and still writes its report here. Its
spike block takes the killfeed fit's clock: since `replay_truth` 0.4.0 the
call passed a constant offset and the command failed. The report:

`score` aligns replay time to capture time through STORED deaths
(`replay_truth.session_context`, the same fit `replay_truth score` reports)
with one constant offset: on 9acf02f98283,
[metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#align_offset_ms=112619.5] ms, 180 of 181 stored
deaths paired, residual MAD [metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#align_mad_ms=145.0] ms.
The capture clock drifts against the replay's: the stored alignment's slope is
1.00013, 282 ms over the match (`align.slope` and `align.drift_ms_over_match`
in analysis/replay-abilities-20261004/9acf02f98283.json), so the constant offset's
timing error spans up to 282 ms across the match. It then scores 9acf02f98283-style stored streams: `tray_drop` player casts,
`ability_state` cast and death verdicts, `ability_shape` Recon Bolt rings and
Hunter's Fury beams, `ult_cast`, `spike` (through `replay_truth.score_spike`),
`smoke`, and the player's own tray-object marks and minimap-glyph labels.
Positions go through `riot_ground_truth.MapFrame` exactly as `replay_truth`
does. Agreement is consistency, not accuracy; disagreements are stored.

`survey` counts the ability classes in every parse (counts only).

What `score` measured on 9acf02f98283
-------------------------------------
Reader accuracy, not a domain fact: the stored `ability_shape` ring of the
player's Recon Bolt is centred a median
[metric:replay_abilities/score#rb_err_px_median=0.96] px from the replay's
stuck bolt, and drawn from about 0.3 s after the bolt opens until about
0.1 s before it closes (medians 315.5 and -108.8 ms over 15 bolts,
`ability_shape.recon_bolt` in analysis/replay-abilities-20261004/
9acf02f98283.json).

Facts this file established
---------------------------
The cast records and their delta replication [domain:replay/vrf-cast-records],
the Recon Bolt's actors [domain:replay/vrf-sova-recon-bolt-actors], the ult
state [domain:replay/vrf-ult-active], the planted spike and ult orbs
[domain:replay/vrf-planted-spike-actor], and the truth each replay carries
[domain:replay/vrf-ability-truth-per-replay]. Keeping replays:
docs/REPLAY_KEEPING.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay_truth as rt  # noqa: E402
import riot_ground_truth as rg  # noqa: E402

# Moved into the acceptance harness (`reticle/harness/abilities.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.abilities import (  # noqa: E402,F401
    _stats, actor_census, ANALYSIS, CAST_GATE_MS, REPLAY_ABILITIES_VERSION, STORE, ULT_GATE_MS)

# The actor reader, the class-to-ability mapping and the cast records live in
# the pipeline (`reticle.replay_actors`) since 2026-10-05; these names stay
# for callers.
from reticle.replay_actors import (CAST_ARRAY, CAST_FIELDS,  # noqa: E402,F401
                                   GAME_BUILD, NON_CHARACTER, PAIR_POST_MS, PAIR_PRE_MS,
                                   ROLE_PREFIX, SLOT_MIN_PAIRED, SLOT_MIN_SHARE, Export, _FOLDER,
                                   _leaf, _role, ability_display, handoff, slot_map)
from reticle.replay_actors import class_census  # noqa: E402


# ----------------------------------------------------------------- score

def score(sid: str) -> dict:
    """`question_acceptance.replay_abilities_score`: the scorer moved into
    the one harness (step 9, task harness-step9-20261009); this name stays
    for callers."""
    import question_acceptance as qa
    return qa.replay_abilities_score(sid)


# ----------------------------------------------------------------- survey

def survey() -> dict:
    """Counts only: ability-folder classes, ult orbs and plants in every parse."""
    rows, per_class = [], defaultdict(Counter)
    rep = json.loads((rt.REPLAYS / "manifest.json").read_text(encoding="utf-8"))
    meta = {Path(f["file"]).stem: f for f in rep["files"]}
    for d in sorted(p for p in rt.PARSED.iterdir() if (p / "export" / "actors.parquet").is_file()):
        ex = Export(d.name, light=True)
        op = ex.a_ev == "open"
        cps = ex.a_cp[op]
        info = meta.get(d.name, {})
        build = (info.get("build") or {}).get("branch", "").rsplit("+", 1)[-1] or None
        cnt = Counter()
        codes = set()
        for cp in cps:
            f = _FOLDER.match(cp)
            short = _leaf(cp)
            if short.endswith("_PC_C") and cp.startswith("/Game/Characters/"):
                codes.add(cp.split("/")[3])
            if f and _role(short) in ("projectile", "game object", "pawn", "ground patch"):
                cnt[short] += 1
            elif cp.rsplit(".", 1)[0] in NON_CHARACTER:
                cnt[short] += 1
        world = sum(v for k, v in cnt.items() if k not in ("UltPointOrb_C", "TimedBomb_C", "BombEquippable_C"))
        rows.append({"match": d.name[:8], "build": build,
                     "map": (info.get("map") or "").rsplit("/", 1)[-1] or None,
                     "capture_session": info.get("capture_session"), "agent_codes": sorted(codes),
                     "ability_world_opens": world, "classes": len(cnt),
                     "ult_orbs": cnt.get("UltPointOrb_C", 0), "plants": cnt.get("TimedBomb_C", 0)})
        for k, v in cnt.items():
            per_class[k][d.name[:8]] = v
    w = np.array([r["ability_world_opens"] for r in rows], float)
    return {"replay_abilities_version": REPLAY_ABILITIES_VERSION, "parsed": len(rows),
            "ability_world_opens": _stats(w, 1), "replays": rows,
            "classes": {k: {"replays": len(v), "opens": sum(v.values())}
                        for k, v in sorted(per_class.items())}}


# ----------------------------------------------------------------- record

def record_census(c: dict) -> list[str]:
    from reticle import metrics
    v = {"classes": len(c["classes"]), "mapped": c["mapped_classes"],
         "unmapped": len(c["unmapped_classes"]),
         "non_player_movement_rows": c["non_player_movement"]["rows"],
         "non_player_pawns": c["non_player_movement"]["pawns"],
         "cast_records": c["casts"]["records"], "ult_transitions": c["ults"]["transitions"],
         "ult_events": c["ults"]["events"],
         "ult_events_within_100ms": c["ults"]["events_within_100ms_of_transition"]}
    v["plant_events"] = c.get("plant_events")
    for r in c["classes"]:
        k = re.sub(r"[^a-z0-9]", "_", r["class"].lower().removesuffix("_c"))
        if r.get("mapped") and r["role"] != "ability item":
            v[f"{k}_opens"] = r["opens"]
            v[f"{k}_life_s_median"] = (r["lifetime_s"] or {}).get("median")
    sm = slot_map(c)
    for key, f in sm.items():
        if f is None:
            continue
        row = c["casts"]["by_agent_slot"][key]
        k = re.sub(r"[^a-z0-9]", "_", key.lower())
        v[f"slot_{k}_paired"] = row.get(f, 0)
        v[f"slot_{k}_casts"] = sum(row.values())
    for key, st in c["casts"]["open_after_cast_ms"].items():
        k = re.sub(r"[^a-z0-9]", "_", key.lower().removesuffix("_c"))
        v[f"open_after_cast_{k}_ms_median"] = (st or {}).get("median")
    for key, h in c["handoff"].items():
        k = re.sub(r"[^a-z0-9]", "_", key.lower().removesuffix("_c"))
        v[f"handoff_{k}_paired"] = h["paired"]
        v[f"handoff_{k}_ms_median"] = (h["open_minus_projectile_close_ms"] or {}).get("median")
        v[f"handoff_{k}_cm_median"] = (h["spawn_to_projectile_location_cm"] or {}).get("median")
        v[f"handoff_{k}_cm_max"] = (h["spawn_to_projectile_location_cm"] or {}).get("max")
    metrics.record("replay_abilities", part="census", session=c["match"][:8], values=v,
                   deps={"replay_abilities": REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION,
                         "game_files": GAME_BUILD})
    return [f"[metric:replay_abilities/census#{k}={x}]" for k, x in v.items()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, arg in (("census", "match"), ("score", "session")):
        p = sub.add_parser(name)
        p.add_argument(arg)
        p.add_argument("--record", action="store_true")
    p = sub.add_parser("survey")
    p.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    rt._below_normal()
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    if args.cmd == "census":
        c = actor_census(args.match)
        (ANALYSIS / f"census-{args.match[:8]}.json").write_text(
            json.dumps(c, indent=1, default=rt._default), encoding="utf-8")
        print(json.dumps({k: v for k, v in c.items() if k != "classes"}, indent=1, default=rt._default))
        for r in c["classes"]:
            print(json.dumps({k: r.get(k) for k in ("class", "role", "opens", "closes", "mapped",
                                                    "unmapped_reason", "rep_movement_rows",
                                                    "movement_rows", "instigator_resolved")},
                             default=rt._default))
        if args.record:
            print("\n".join(record_census(c)))
        return 0
    if args.cmd == "score":
        # the scorer is the harness's (`question_acceptance.py replay-abilities`)
        import question_acceptance as qa
        return qa.main(["replay-abilities", args.session, "--legacy-out"]
                       + (["--record-score"] if args.record else []))
    if args.cmd == "survey":
        sv = survey()
        (ANALYSIS / "survey.json").write_text(json.dumps(sv, indent=1, default=rt._default),
                                              encoding="utf-8")
        for r in sv["replays"]:
            print(json.dumps(r))
        print(json.dumps({k: v for k, v in sv["classes"].items()}, indent=0)[:6000])
        if args.record:
            from reticle import metrics
            v = {"parsed": sv["parsed"], "world_opens_median": sv["ability_world_opens"]["median"],
                 "world_opens_min": min(r["ability_world_opens"] for r in sv["replays"]),
                 "classes": len(sv["classes"])}
            metrics.record("replay_abilities", part="survey", values=v,
                           deps={"replay_abilities": REPLAY_ABILITIES_VERSION, "vrfkit": rt.VRFKIT_VERSION})
            print(" ".join(f"[metric:replay_abilities/survey#{k}={x}]" for k, x in v.items()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
