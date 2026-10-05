r"""Stage 1 of docs/MINIMAP_GLYPH_CHANNEL.md: the per-key rotation policy table and the per-key null table, from dev.

    .\.venv\Scripts\python.exe prototypes\glyph_tables.py build  --out DIR   (both tables; storage only, no cache)
    .\.venv\Scripts\python.exe prototypes\glyph_tables.py follow --out DIR   (S1 follow, S4, the pooled null; crop cache)
    .\.venv\Scripts\python.exe prototypes\glyph_tables.py thrown --out DIR   (S5; crop cache of the match sessions)
    .\.venv\Scripts\python.exe prototypes\glyph_tables.py record --out DIR   (metric series glyph_tables/*, once)
    .\.venv\Scripts\python.exe prototypes\glyph_tables.py bank --out NEWDIR --tables DIR   (the references, as data)

`bank` writes `glyph-bank-0.3.1.npz` and `.json`: the 128 px glyphs the tables in DIR were built on, each with its
game file and sha256, which the
stage 2 reader (`reticle.minimap_glyph`) reads as versioned data; the reader never imports this script.

`build` writes `glyph-rotation-policy-0.1.2.json` and `glyph-null-table-0.2.1.json` under DIR and `build.json`
(the single-frame measurements S1-S3 and the instrument controls). Each command refuses an output that exists,
so a rerun goes to a new DIR; `follow`, `thrown` and `record` read the tables `build` wrote in the same DIR. `build`
reads the dev crop cache for the unlabelled discs (no decode); `follow` and `thrown` still score at the widget scale
(minimap-glyph-follow-0.2.0) and were not rerun at 0.2.0.

**0.2.0, the stage 3 prerequisites** (glyph-prereqs-20261005). Every null score is taken at the item's session's
`geometry.MapScale.scale` (widget x map zoom; `to_map_scale`, the table's `basis` map_scale), so the reader's one
transform reads cuts measured at its own basis; the instrument controls still run at the widget scale and must
reproduce stage 1 (58, 55 and 35 of 59). Beside the labelled no-ability discs, the null takes the proposer discs of
the dev sessions' exhaustive paint frames that no painted icon or labelled item explains and the reader's own gates
keep (`unlabelled_negatives`, source `paint_exhaustive_unlabelled`): the player painted every icon on those frames,
so such a disc is no ability. Only d95cfad5693a holds such frames; dae6f33f3f48 has none, and no other evidence
vouches for an unlabelled disc there. The audit null (`audit_null`) scores the same discs against every key at every
rotation: each key's `audit_cut` and the audit bank's cut.

**The policy table** (`policy_rows`), one row per catalogue key (the game's DisplayIcon keys, slots C, Q, E, X):
a sure player rotation answer decides (labels/minimap_glyph_questions/answers.jsonl, `rotation:*` rows, last row
wins, each row's line cited, each answer a domain fact, `ANSWER_FACTS`:
[domain:abilities/cypher-spycam-minimap-glyph-turns] [domain:abilities/omen-dark-cover-minimap-glyph-turns]
[domain:abilities/killjoy-alarmbot-minimap-glyph-turns] [domain:abilities/deadlock-sonic-sensor-square-follows-wall]
[domain:abilities/deadlock-gravnet-minimap-glyph-upright] [domain:abilities/reyna-leer-minimap-glyph-upright]
[domain:abilities/skye-guiding-light-minimap-glyph-upright] [domain:abilities/skye-trailblazer-minimap-glyph-upright]
[domain:abilities/sova-owl-drone-minimap-glyph-upright], and from 0.1.2
[domain:abilities/skye-seekers-minimap-glyph-turns-belief] [domain:abilities/cypher-cyber-cage-minimap-glyph-turns-belief]
[domain:abilities/cypher-trapwire-minimap-glyph-turns-belief]); Deadlock:Q, "normal to the wall", is
searched at every rotation because no sonic-square wall fit is in master; an unsure answer (none from 0.1.2;
Cypher:C and Skye:X until 0.1.1) is
searched at every rotation with the reason `unsure_pending_player`; every other key follows the two-flag rule
(`glyph_channel_cost.rule_verdict` over the raw export's minimap components, `rule_per_key`): upright when every
component reads upright; every rotation when any component turns, the components disagree (`mixed`) or a
RotationSource the rule does not read leaves it `undetermined`. A key no minimap component draws is upright by
default, unverified (`decided_by` `no_component_default`), never a rule decision. A sure answer the rule contradicts is stored on its row as a surprise against the hypothesis.

**The null table** (`null_table`), from the eval 0.3.0 dev windows only (store
analysis/minimap-glyphs-killjoy-refs-20261004/gamedata-on, minimap-glyph-eval-0.3.0, gamedata and answers on;
labels/ability, labels/ability_paint and labels/tray_object of the dev sessions d95cfad5693a and dae6f33f3f48):
every disc the player labelled as no ability, scored single frame (masked Pearson of luma, the eval's matcher)
against every catalogue key at its policy's search size. Each key's cut sits where at most 5% of those discs
score above it (`cut_at`): a key names a disc when its score exceeds its cut. Per key the bank's false naming
adds up across keys, so each bank (the labelled caster's kit, `context`, and every key, `full`) also gets its own
cut, overall and at each widget scale: the `cut_at` of each disc's best score within the bank, so that at most 5%
of the discs' best keys clear it (gate 3's bank form). The table gives each bank's false-naming rate at the per-key
cuts, at the bank cut and with the tie margin, the margin distributions, the tie margin, and `gate3`, which parts
of gate 3 this table meets and which it does not (no unlabelled proposer disc enters; the follow's pooled bank cut
is in follow.json). The dev sessions are demos of Cypher and Killjoy: no audio-borrowed label exists on them (the label
path covers only the player's own Sova and Skye casts), so none enters.

**No held-out label enters either table.** The held-out sessions are every session of the held-out labelling
pass (labels/minimap_glyph_heldout) other than the two dev sessions (`heldout_pass`), and every session of the
eval's own held-out split (`eval_heldout_split`: each session of the eval's label sources outside dev).
`table_provenance` lists the dev sessions, names the held-out ones and the match sessions stage 1's S5 used
(`s5_match_sessions`, which gate 4's fresh set excludes), and asserts that every scored item is a dev item from
the eval's label sources; the builder reads labels/minimap_glyph_heldout only for its file names.

`follow` reruns the eval's follow (`minimap_glyph_eval.follow_item`, minimap-glyph-follow-0.2.0) on the dev
positives and no-ability discs with the policy table's rotations, at the crop cache's cadence and over the 2 Hz
frames alone (every 500 ms from the labelled frame), beside the rotate-all control that must reproduce 58 of 59;
the no-ability discs' pooled scores give the pooled null. `thrown` seeds the follow at the thrown icon instead of
the self icon on the matches' own glyph casts (`thrown_seed`), the tray drop's slot as truth.

Predictions: store notes/predictions.jsonl, glyph-wiring-design-fix-20261004 S1-S5. Wire: no (stage 1 builds
the tables the stage 2 reader, `minimap_glyph`, will read; the tables are its inputs, this script is not).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import glyph_channel_cost as gcc  # noqa: E402  (sets single-threaded, Below Normal)
import minimap_glyph_eval as mge  # noqa: E402
import numpy as np  # noqa: E402

VERSION = "glyph-tables-0.2.1"   # 0.2.0: the null at the full transform, unlabelled discs, the audit null
#: 0.2.1: the three 2026-10-05 rotation answers; build.json compares every cut with glyph-null-table-0.2.0's.
#: 0.1.1: no_component_default. The stamp versions the rows: at glyph-tables-0.2.0 the rows are unchanged and the
#: file differs from 0.1.1's only in its provenance (generator); the bank's sha256 pairing pins each file's bytes.
#: 0.1.2: rows Skye:X, Cypher:Q and Cypher:C decided by the player's 2026-10-05 answers (L472-L474).
POLICY_VERSION = "glyph-rotation-policy-0.1.2"
#: 0.1.1: bank cuts (gate 3), fuller provenance. 0.2.0: every score at geometry.MapScale.scale (widget x map zoom,
#: `basis` map_scale), the unlabelled proposer discs of the dev sessions' exhaustive paint frames, and the audit
#: null (`keys.<key>.audit_cut`, `banks.audit`).
#: 0.2.1: the rule and basis of 0.2.0 over policy 0.1.2 (Cypher:Q rotated).
NULL_VERSION = "glyph-null-table-0.2.1"
BASIS = "map_scale"
FALSE_RATE = 0.05        # a design choice (docs/MINIMAP_GLYPH_CHANNEL.md, gate 3)
DEV_RUN = gcc.KILLJOY_REFS_DEV.parent
HELDOUT_LABELS = mge.LABELS / "minimap_glyph_heldout"
EVAL_SOURCES = {"ability", "paint", "tray_object"}
UNSURE = "unsure_pending_player"
NO_COMPONENT = "no_component_default"
NO_COMPONENT_REASON = "no minimap component draws this key; upright by default, unverified"
TWO_HZ_MS = 500.0        # the ability pass's cadence
#: Each sure rotation answer's domain fact (domain/abilities.toml); the table cites it beside the answer's line.
ANSWER_FACTS = {"Cypher:E": "abilities/cypher-spycam-minimap-glyph-turns",
                "Omen:E": "abilities/omen-dark-cover-minimap-glyph-turns",
                "Killjoy:Q": "abilities/killjoy-alarmbot-minimap-glyph-turns",
                "Deadlock:Q": "abilities/deadlock-sonic-sensor-square-follows-wall",
                "Deadlock:C": "abilities/deadlock-gravnet-minimap-glyph-upright",
                "Reyna:C": "abilities/reyna-leer-minimap-glyph-upright",
                "Skye:E": "abilities/skye-guiding-light-minimap-glyph-upright",
                "Skye:Q": "abilities/skye-trailblazer-minimap-glyph-upright",
                "Sova:C": "abilities/sova-owl-drone-minimap-glyph-upright",
                # Answered 2026-10-05 (answers.jsonl#L472, L473, L474); glyph-rotation-policy-0.1.2 reads them.
                "Skye:X": "abilities/skye-seekers-minimap-glyph-turns-belief",
                "Cypher:Q": "abilities/cypher-cyber-cage-minimap-glyph-turns-belief",
                "Cypher:C": "abilities/cypher-trapwire-minimap-glyph-turns-belief"}
WALL_NORMAL = "normal to the wall"
TABLES = (f"{POLICY_VERSION}.json", f"{NULL_VERSION}.json")


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def catalogue_keys() -> list[str]:
    return sorted(f"{a}:{s}" for a, s in mge.GLYPHS if s in "CQEX")


# ------------------------------------------------------------------ the rotation policy


def rotation_answer_rows(path: Path = None) -> dict:
    """{key: {line, answer, unsure, other, ts}} from the `rotation:*` rows of the answers file, last row wins;
    `line` is the 1-based line of the row that wins."""
    out = {}
    for i, ln in enumerate(Path(path or mge.ANSWERS).read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("kind") == "rotation":
            out[r["key"].split(":", 1)[1]] = {"line": i, "answer": r.get("answer"), "unsure": bool(r.get("unsure")),
                                              "other": r.get("other"), "ts": r.get("ts")}
    return out


def rule_policy(verdict: str) -> str:
    """The two-flag rule's search: upright only when every component reads upright (or none draws the key)."""
    return "upright" if verdict in ("upright", "no_component") else "rotates"


def policy_rows(keys: list[str], answers: dict, verdicts: dict, evidence: dict) -> list[dict]:
    """One row per key: `policy` (rotates or upright), its `rotations`, `decided_by`, `reason`, the answer row
    (`answer`, with its line) and domain fact it rests on, the rule's verdict and component evidence, and a
    `surprise` where a sure answer contradicts the rule. Pure over its inputs."""
    rows = []
    for k in keys:
        v = verdicts.get(k, "no_component")
        rp = rule_policy(v)
        a = answers.get(k)
        row = {"key": k, "rule": {"verdict": v, "policy": rp, "components": evidence.get(k, [])},
               "answer": a, "domain": None, "surprise": None}
        if a and a["unsure"]:
            row.update(policy="rotates", decided_by=UNSURE, reason=UNSURE)
        elif a and a["answer"] in ("rotates", "upright"):
            row.update(policy=a["answer"], decided_by="player_answer", reason=f"player answered {a['answer']}",
                       domain=ANSWER_FACTS.get(k))
        elif a and a["answer"] == "other" and WALL_NORMAL in (a.get("other") or ""):
            row.update(policy="rotates", decided_by="player_answer",
                       reason="player: always normal to the wall, any angle; no sonic-square wall fit is in master "
                              "(sonic-square-20261004), so every rotation", domain=ANSWER_FACTS.get(k))
        elif a and a["answer"] is not None:
            row.update(policy="rotates", decided_by="player_answer_unread",
                       reason=f"answer {a['answer']!r} ({a.get('other')!r}) has no reading here; every rotation")
        elif v == "no_component":
            row.update(policy="upright", decided_by=NO_COMPONENT, reason=NO_COMPONENT_REASON)
        else:
            row.update(policy=rp, decided_by="two_flag_rule", reason=f"two_flag_rule:{v}")
        if row["decided_by"] == "player_answer" and k in verdicts and rp != row["policy"]:
            row["surprise"] = f"the answer ({row['policy']}) contradicts the two-flag rule ({v}: {rp})"
        row["rotations"] = list(mge.ROTS) if row["policy"] == "rotates" else [0]
        rows.append(row)
    return rows


def eval_heldout_split(dev: set) -> list[str]:
    """The eval's own held-out split: every session of its label sources (`minimap_glyph_eval.load_items`) outside
    dev. The labels are read for their session ids only; none is scored."""
    return sorted({it["sid"] for it in mge.load_items() if it["sid"] not in dev})


def s5_match_sessions(path: Path = None) -> list[str]:
    """The match sessions stage 1's S5 (`thrown`) used: every session of a glyph cast in the cross-channel casts."""
    p = Path(path or gcc.CROSS_CASTS)
    if not p.exists():
        return []
    rows = [json.loads(ln) for ln in open(p, encoding="utf-8") if ln.strip()]
    return sorted({r["sid"] for r in rows if r.get("kind") == "match" and r.get("B_source") == "glyph"})


def heldout_sessions(dev: set, eval_split: list[str] | None = None, s5: list[str] | None = None) -> dict:
    """The held-out sessions: the held-out labelling pass's (file names only, never read), the eval's own held-out
    split, and the match sessions S5 used (not held out from the tables, which never read them; listed so gate 4's
    fresh set excludes them)."""
    hp = sorted(p.stem for p in HELDOUT_LABELS.glob("*.jsonl") if p.stem not in dev)
    return {"heldout_pass": hp, "heldout_pass_dir": str(HELDOUT_LABELS),
            "eval_heldout_split": sorted(eval_split) if eval_split is not None else eval_heldout_split(dev),
            "s5_match_sessions": sorted(s5) if s5 is not None else s5_match_sessions(),
            "note": "the held-out pass also labelled the two dev sessions (its dev_session subset); those rows are "
                    "never read: the dev items come from labels/ability, ability_paint and tray_object. "
                    "s5_match_sessions are used by stage 1 (S5) and excluded from gate 4's fresh set"}


def table_provenance(answers: dict, dev_items: list[dict], dev: set, used_lines: list[int],
                     eval_split: list[str] | None = None, s5: list[str] | None = None) -> dict:
    """What both tables rest on, with the proof that no held-out label enters: every item is a dev item from the
    eval's own label sources, and no item's session is held out."""
    ho = heldout_sessions(dev, eval_split, s5)
    sids = sorted({r["sid"] for r in dev_items})
    held = set(ho["heldout_pass"]) | set(ho["eval_heldout_split"])
    bad = [r for r in dev_items if r["sid"] not in dev or r["split"] != "dev" or r["src"] not in EVAL_SOURCES
           or r["sid"] in held]
    if bad:
        raise SystemExit(f"{len(bad)} non-dev items reached the tables, e.g. {bad[0]['sid']} {bad[0]['t_ms']}")
    return {"generator": VERSION, "build": mge.BUILD, "eval": mge.VERSION,
            "answers": {"file": str(mge.ANSWERS), "sha256": sha256(mge.ANSWERS), "lines": sorted(used_lines)},
            "gamedata": {"raw_export": str(gcc.STATES_TABLE.parent.parent / "game-files" / mge.BUILD / "ability-states"),
                         "states_table": gcc.STATES_TABLE.name},
            "dev_sessions": sids, "dev_split": sorted(dev),
            "dev_run": {"items": str(DEV_RUN / "items.json"), "items_sha256": sha256(DEV_RUN / "items.json"),
                        "windows": str(DEV_RUN / "windows.npz")},
            "label_sources": sorted({r["src"] for r in dev_items}),
            "heldout_sessions": ho, "heldout_items_used": 0, "heldout_sessions_used": [],
            "borrowed_labels": "none: the dev sessions are Cypher and Killjoy demos; audio labels cover only the "
                               "player's own Sova and Skye casts"}


# ------------------------------------------------------------------ single-frame scores and the null


def key_scores(items: list[dict], z, keys: list[str], rotating: set) -> tuple[dict, dict]:
    """({win_index: per-key best score over shifts, sources, canvases and the key's rotations}, {scale: {key:
    templates}}), every item scored against every key in `keys` (rotated when in `rotating`)."""
    tk = [tuple(k.split(":")) for k in keys]
    idx = {k: i for i, k in enumerate(tk)}
    mge.ROTATING = {tuple(k.split(":")) for k in rotating}
    banks, sizes, out = {}, {}, {}
    for r in items:
        s = round(r["scale"], 3)
        if s not in banks:
            T, meta = mge.bank(r["scale"], tk, rotate="policy")
            banks[s] = (mge.zrows(T), np.array([idx[m[0]] for m in meta]))
            sizes[s] = {keys[i]: int(n) for i, n in enumerate(np.bincount(banks[s][1], minlength=len(keys)))}
        P = mge.patches(r["Yw"] if "Yw" in r else z["Y"][r["win_index"]], r["scale"])
        if P is None:
            continue
        Tz, owner = banks[s]
        S = (mge.zrows(P) @ Tz.T).max(0)
        per = np.full(len(keys), -2.0, np.float32)
        np.maximum.at(per, owner, S)
        out[r["win_index"]] = per
    return out, sizes


def cut_at(scores, rate: float = FALSE_RATE) -> float | None:
    """The cut a key names above: the (m+1)-th highest null score, m = floor(rate x n), so at most m of the n
    scores exceed it; None without scores."""
    s = np.sort(np.asarray(scores, float))[::-1]
    if not len(s):
        return None
    return float(s[min(int(np.floor(rate * len(s))), len(s) - 1)])


def best_in(per: np.ndarray, keys: list[str], allowed: list[str]) -> tuple[str, float, float]:
    """(best key, its score, margin over the runner-up) within `allowed`."""
    ix = [keys.index(k) for k in allowed]
    v = per[ix]
    o = np.argsort(-v)
    return allowed[o[0]], float(v[o[0]]), float(v[o[0]] - (v[o[1]] if len(o) > 1 else -1.0))


def q(v, ps=(50, 90, 95)) -> dict:
    return {f"p{p}": round(float(np.percentile(v, p)), 4) for p in ps} if len(v) else {}


def null_table(neg: list[dict], pos: list[dict], sc: dict, sizes: dict, keys: list[str], policy: dict) -> dict:
    """Per key: the no-ability discs' score distribution and the cut (`cut_at`), overall and per widget scale;
    per bank: the false-naming rate at the cuts and the margin distributions; the tie margin."""
    neg = [r for r in neg if r["win_index"] in sc]
    out = {"version": NULL_VERSION, "policy_version": POLICY_VERSION, "rate": FALSE_RATE, "basis": BASIS,
           "basis_rule": "every px x scale length (mask, shift, canvas) at geometry.MapScale.scale of the item's "
                         "session: widget scale x map zoom, one transform",
           "rule": "a key names a disc when its score exceeds its cut; the cut is the (m+1)-th highest score of "
                   "the dev no-ability discs against that key, m = floor(rate x n)",
           "score": "single frame: masked Pearson of luma, r = 8.5 px x scale, +-3 px centre, canvas 11-22 px x "
                    "scale, the key's policy rotations (minimap-glyph-eval-0.3.0's matcher)",
           "negatives": {"n": len(neg), "by_session": dict(Counter(r["sid"] for r in neg)),
                         "by_scale": dict(Counter(str(round(r["scale"], 4)) for r in neg)),
                         "by_source": dict(Counter(r["src"] for r in neg))},
           "keys": {}}
    M = np.array([sc[r["win_index"]] for r in neg])
    scales = sorted({round(r["scale"], 3) for r in neg})
    for j, k in enumerate(keys):
        col = M[:, j]
        c = cut_at(col)
        e = {"policy": policy[k], "templates": {str(s): sizes[s][k] for s in sizes}, "n": int(len(col)),
             "cut": round(c, 4), "named_at_cut": int((col > c).sum()),
             "rate_at_cut": round(float((col > c).mean()), 4), **q(col), "max": round(float(col.max()), 4),
             "by_scale": {}}
        for s in scales:
            m = np.array([round(r["scale"], 3) == s for r in neg])
            e["by_scale"][str(s)] = {"n": int(m.sum()), "cut": round(cut_at(col[m]), 4)}
        out["keys"][k] = e
    cut = {k: out["keys"][k]["cut"] for k in keys}
    wrong = []
    for r in pos:
        if r["win_index"] in sc:
            b, s, m = best_in(sc[r["win_index"]], keys, r["kit"])
            if b != r["truth"]:
                wrong.append(m)
    tie = round(max(wrong), 4) if wrong else None
    out["tie_margin"] = {"value": tie, "reason": None if wrong else "no_wrong_dev_item_single_frame",
                         "rule": "the largest margin of a wrongly named dev glyph item (context bank); a verdict "
                                 "names only above it", "wrong_items": len(wrong)}
    out["banks"] = {}
    for bank in ("context", "full"):
        named, verdict, margins, best = Counter(), Counter(), [], []
        for r in neg:
            b, s, m = best_in(sc[r["win_index"]], keys, r["kit"] if bank == "context" else keys)
            margins.append(m)
            best.append(s)
            if s > cut[b]:
                named[b] += 1
                if tie is None or m > tie:
                    verdict[b] += 1
        pos_named = [r for r in pos if r["win_index"] in sc and (lambda b, s, m: b == r["truth"] and s > cut[b] and
                     (tie is None or m > tie))(*best_in(sc[r["win_index"]], keys, r["kit"] if bank == "context" else keys))]
        out["banks"][bank] = {"n": len(neg),
                              "false_named_cut": sum(named.values()),
                              "false_naming_rate_cut": round(sum(named.values()) / max(len(neg), 1), 4),
                              "named_as_cut": dict(named),
                              "false_named_verdict": sum(verdict.values()),
                              "false_naming_rate_verdict": round(sum(verdict.values()) / max(len(neg), 1), 4),
                              "named_as_verdict": dict(verdict), "negative_margin": q(margins),
                              "glyph_items_named_right_verdict": len(pos_named), "glyph_items": len(pos),
                              "bank_cut": bank_cut(neg, pos, sc, keys, bank, np.array(best))}
    out["gate3"] = gate3(out)
    return out


def bank_cut(neg: list[dict], pos: list[dict], sc: dict, keys: list[str], bank: str, best: np.ndarray) -> dict:
    """Gate 3's bank form: one cut for the bank, the `cut_at` of each no-ability disc's best score within the bank,
    so at most FALSE_RATE of the discs' best keys clear it; overall and at each widget scale (each scale's discs
    against their own cut). Beside it, the dev glyph items the bank's best key names right above the cut."""
    c = cut_at(best)
    scl = np.array([round(r["scale"], 3) for r in neg])
    by = {}
    for s in sorted(set(scl.tolist())):
        m = scl == s
        cs = cut_at(best[m])
        by[str(s)] = {"n": int(m.sum()), "cut": round(cs, 4), "named": int((best[m] > cs).sum()),
                      "rate": round(float((best[m] > cs).mean()), 4),
                      "allowed": int(np.floor(FALSE_RATE * m.sum()))}
    per_scale_named = sum(v["named"] for v in by.values())
    cut_of = {k: v["cut"] for k, v in by.items()}
    pz = [r for r in pos if r["win_index"] in sc]
    right_cut, right_scale = 0, 0
    for r in pz:
        b, s, _ = best_in(sc[r["win_index"]], keys, r["kit"] if bank == "context" else keys)
        if b == r["truth"]:
            right_cut += s > c
            cs = cut_of.get(str(round(r["scale"], 3)))
            right_scale += cs is not None and s > cs
    return {"rule": "a disc is named when its best score within the bank exceeds the bank cut",
            "cut": round(c, 4), "n": int(len(best)), "named": int((best > c).sum()),
            "rate": round(float((best > c).mean()), 4), "by_scale": by,
            "per_scale_named": per_scale_named, "per_scale_rate": round(per_scale_named / max(len(best), 1), 4),
            "glyph_items_named_right_cut": int(right_cut), "glyph_items_named_right_per_scale": int(right_scale),
            "glyph_items": len(pz)}


def gate3(ntab: dict) -> dict:
    """Which parts of gate 3 (docs/MINIMAP_GLYPH_CHANNEL.md section 5) this null table meets, from its own fields."""
    b = {k: v for k, v in ntab["banks"].items() if k in ("context", "full")}
    n_un = (ntab["negatives"].get("by_source") or {}).get(UNLABELLED_SRC, 0)
    return {"bank_cut_at_most_rate": all(b[k]["bank_cut"]["rate"] <= FALSE_RATE for k in b),
            "per_scale_bank_cut_at_most_rate": all(v["rate"] <= FALSE_RATE for k in b for v in b[k]["bank_cut"]["by_scale"].values()),
            "per_key_cut_bank_rate_at_most_rate": all(b[k]["false_naming_rate_cut"] <= FALSE_RATE for k in b),
            "unlabelled_proposer_discs": n_un > 0,
            "unlabelled_n": n_un,
            "pooled_score": "follow.json pooled_null (labelled no-ability discs only; not rerun at 0.2.0)",
            "note": "the per-key cuts alone do not hold a bank at the rate; the bank cut does by construction. "
                    "Unlabelled proposer discs come only from frames the player painted exhaustively "
                    "(`unlabelled_negatives`); a disc the reader's gates refuse never reaches a cut and stays out"}


UNLABELLED_SRC = "paint_exhaustive_unlabelled"


def to_map_scale(items: list[dict]) -> dict:
    """Rescale every item to its session's geometry.MapScale.scale in place (`widget_scale` keeps the crop's);
    refuses an item whose crop width disagrees with the key's widget. Returns {sid: MapScale provenance}."""
    from reticle import geometry
    ms = {}
    for r in items:
        if r["sid"] not in ms:
            m = geometry.map_scale_of(r["sid"], str(mge.STORE))
            if m is None:
                raise SystemExit(f"{r['sid']}: no geometry.MapScale")
            ms[r["sid"]] = m
        m = ms[r["sid"]]
        ws = r.get("widget_scale", r["scale"])
        if abs(ws - m.widget_scale) > 1e-3:
            raise SystemExit(f"{r['sid']}: crop scale {ws} is not the key's widget scale {m.widget_scale}")
        r["widget_scale"], r["scale"], r["map_zoom"] = ws, m.scale, m.map_zoom
    return {s: m.provenance() for s, m in ms.items()}


def exhaustive_paint_frames(sid: str) -> dict:
    """{t_ms: the latest `frame` row of labels/ability_paint at that time, where that row is exhaustive and sure}: the
    frames on which the player painted every ability icon, so a proposer disc no painted icon explains is no ability.
    The latest row decides, so a later non-exhaustive or unsure row retracts an earlier exhaustive one."""
    p = mge.LABELS / "ability_paint" / f"{sid}.jsonl"
    latest = {}
    if not p.exists():
        return latest
    for ln in open(p, encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            if r.get("kind") == "frame":
                latest[float(r["t_ms"])] = r
    return {t: r for t, r in latest.items() if r.get("exhaustive") and not r.get("unsure")}


def unlabelled_negatives(dev_items: list[dict], dev: set) -> tuple[list[dict], dict]:
    """(items, report): proposer discs (`ability_icons.propose_icons`) of the dev sessions' exhaustive paint frames
    that lie farther than SNAP_R x scale from every painted icon (the self icon included) and every labelled dev item
    of that frame, and that the reader's own gate decision (`reticle.minimap_glyph.disc_gates`, its owner, over the
    baked static and footprint and the painted self icon as the frame's portrait) does not refuse. Each is a
    no-ability disc no label names: the player's exhaustive paint says nothing else is drawn there. Each item carries its luma window (`Yw`, WIN half-size) and the
    session's caster kit as its context bank. Scale is geometry.MapScale.scale."""
    import cv2
    from reticle import ability_icons, geometry
    from reticle import minimap_glyph as G
    items, rep = [], {"rule": "exhaustive paint frames only (labels/ability_paint `exhaustive` true); farther than "
                              "SNAP_R x MapScale.scale from every painted icon and labelled item; not gated by the "
                              "reader's gate decision (reticle.minimap_glyph.disc_gates: static_like, map_shown, "
                              "the painted self icon's portrait cover)",
                      "snap_r": mge.SNAP_R, "sessions": {}}
    for sid in sorted(dev):
        frames_ = exhaustive_paint_frames(sid)
        kits = {tuple(r["kit"]) for r in dev_items if r["sid"] == sid and r.get("kit")}
        s_rep = {"frames": len(frames_), "discs": 0, "near_label": 0, "gated": Counter(), "kept": 0,
                 "kit": [list(k) for k in sorted(kits)]}
        rep["sessions"][sid] = s_rep
        if not frames_:
            continue
        if len(kits) != 1:
            raise SystemExit(f"{sid}: the dev items name {len(kits)} kits; an unlabelled disc's context is unknown")
        kit = list(next(iter(kits)))
        c, why, _ = mge.crop_cache(sid)
        cr = c.rect_of("minimap")
        ms = geometry.map_scale_of(sid, str(mge.STORE))
        st = geometry.reference_static(sid, str(mge.STORE))
        sY = mge.luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
        fp = geometry.footprint(sid, str(mge.STORE), shape=st.shape[:2])
        fr = mge.frames(sid, sorted(frames_))
        for t, prow in sorted(frames_.items()):
            th, crop = fr[t]
            roi = prow["roi"]
            painted = [(i["x"] + roi[0] - cr[0], i["y"] + roi[1] - cr[1], i["category_id"]) for i in prow["icons"]]
            lab = [(r["cx"], r["cy"]) for r in dev_items if r["sid"] == sid and abs(r["t_held"] - th) < 1.0]
            Y = mge.luma(crop)
            tm = mge.icon_terms(sid, crop.shape)
            for q in ability_icons.propose_icons(crop, tm):
                s_rep["discs"] += 1
                x, y = float(q["cx"]), float(q["cy"])
                near = [np.hypot(x - a, y - b) for a, b, _ in painted] + [np.hypot(x - a, y - b) for a, b in lab]
                if near and min(near) <= mge.SNAP_R * ms.scale:
                    s_rep["near_label"] += 1
                    continue
                selfs = [(p[0], p[1]) for p in painted if p[2] == "world:self"]
                g = G.disc_gates(Y, [[x, y]], [float(q["r"])], ms.scale, static_y=sY, footprint=fp,
                                 portraits=(["self"] * len(selfs), selfs))
                if g["static_mismatch"] or g["footprint_mismatch"] or fp is None:
                    raise SystemExit(f"{sid}: the baked static or footprint does not fit the crop; the gates are unknown")
                gate = g["why"][0]
                if gate is not None:
                    s_rep["gated"][gate] += 1
                    continue
                ix, iy = int(round(x)), int(round(y))
                Yw = np.full((2 * mge.WIN + 1, 2 * mge.WIN + 1), np.nan, np.float32)
                ya, xa = max(0, iy - mge.WIN), max(0, ix - mge.WIN)
                sub = Y[ya:iy + mge.WIN + 1, xa:ix + mge.WIN + 1]
                Yw[ya - (iy - mge.WIN):ya - (iy - mge.WIN) + sub.shape[0],
                   xa - (ix - mge.WIN):xa - (ix - mge.WIN) + sub.shape[1]] = sub
                items.append({"sid": sid, "t_ms": t, "t_held": th, "cx": x, "cy": y, "r": float(q["r"]),
                              "cat": "NOT", "split": "dev", "src": UNLABELLED_SRC, "kit": kit,
                              "scale": crop.shape[1] / 465.0, "win_index": f"u{len(items)}", "Yw": Yw})
                s_rep["kept"] += 1
        s_rep["gated"] = dict(s_rep["gated"])
    rep["n"] = len(items)
    return items, rep


def audit_null(neg: list[dict], pos: list[dict], sc: dict, keys: list[str]) -> dict:
    """The audit's null: every key at every rotation (the audit path's search size). Per key, the `cut_at` of the
    no-ability discs' scores; for the bank (every key), the `cut_at` of each disc's best score, and the dev glyph
    items whose best key over every kit is right and clears it."""
    neg = [r for r in neg if r["win_index"] in sc]
    M = np.array([sc[r["win_index"]] for r in neg])
    per = {k: round(cut_at(M[:, j]), 4) for j, k in enumerate(keys)}
    best = M.max(1)
    c = cut_at(best)
    right = [r for r in pos if r["win_index"] in sc and best_in(sc[r["win_index"]], keys, keys)[0] == r["truth"]]
    clear = [r for r in right if best_in(sc[r["win_index"]], keys, keys)[1] > c]
    return {"keys": per, "bank_cut": {"rule": "a disc is named when its best score over every key at every rotation "
                                              "exceeds the bank cut", "cut": round(c, 4), "n": int(len(best)),
                                      "named": int((best > c).sum()), "rate": round(float((best > c).mean()), 4),
                                      **q(best), "glyph_items_best_right": len(right),
                                      "glyph_items_named_right_cut": len(clear), "glyph_items": len(pos)},
            "median_key_cut": round(float(np.median(list(per.values()))), 4)}


#: The null table this build's cuts are compared with (`cut_moves`): master's before the 2026-10-05 answers.
PREV_NULL = Path(mge.STORE) / "analysis" / "glyph-tables-20261005c" / "glyph-null-table-0.2.0.json"


def cut_moves(prev: Path, ntab: dict, keys: list[str]) -> dict | None:
    """How this null table's cuts differ from `prev`'s: the median and largest per-key move, each key whose per-key
    or audit cut moved (old, new), and each bank cut (old, new). None when `prev` is absent."""
    if not Path(prev).exists():
        return None
    old = json.load(open(prev, encoding="utf-8"))
    both = [k for k in keys if k in old["keys"]]
    dv = [abs(ntab["keys"][k]["cut"] - old["keys"][k]["cut"]) for k in both]
    moved = {k: {"old": old["keys"][k]["cut"], "new": ntab["keys"][k]["cut"]}
             for k in both if ntab["keys"][k]["cut"] != old["keys"][k]["cut"]}
    amoved = {k: {"old": old["keys"][k].get("audit_cut"), "new": ntab["keys"][k].get("audit_cut")}
              for k in both if ntab["keys"][k].get("audit_cut") != old["keys"][k].get("audit_cut")}
    banks = {b: {"old": old["banks"][b]["bank_cut"]["cut"], "new": ntab["banks"][b]["bank_cut"]["cut"]}
             for b in ("context", "full", "audit") if b in old["banks"] and b in ntab["banks"]}
    return {"from": str(prev), "from_version": old.get("version"), "median_abs": round(float(np.median(dv)), 4),
            "max_abs": round(float(max(dv)), 4), "keys": len(dv), "moved": moved, "audit_moved": amoved,
            "bank_cut": banks}


def load_dev():
    """(items.json, windows) of the eval 0.3.0 dev run, with the references (gamedata, answers) it was built on."""
    d, z = mge.load_scores(DEV_RUN)
    if d["meta"]["version"] != "minimap-glyph-eval-0.3.0" or not d["meta"].get("gamedata"):
        raise SystemExit(f"{DEV_RUN} is not the eval 0.3.0 gamedata-on run")
    items = [r for r in d["items"] if not r.get("refused") and r.get("kit")]
    return d, z, items


def split_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    dev = [r for r in items if r["split"] == "dev"]
    return [r for r in dev if r["cat"] == "NOT"], mge.positives(dev, "dev")


def fresh_all(out: Path, names) -> None:
    for n in names:
        gcc.fresh(out / n)


def cmd_build(out: Path) -> None:
    """Both tables, and S1-S3 single frame with the instrument controls (build.json)."""
    fresh_all(out, (*TABLES, "build.json"))
    t0 = time.time()
    keys = catalogue_keys()
    comps = gcc.minimap_components()
    evidence, verdicts = gcc.rule_per_key(comps, gcc.texture_keys())
    answers = rotation_answer_rows()
    rows = policy_rows(keys, answers, verdicts, evidence)
    policy = {r["key"]: r["policy"] for r in rows}
    rotating = {k for k, p in policy.items() if p == "rotates"}
    d, z, items = load_dev()                         # rebuilds the references the dev run used
    neg, pos = split_items(items)
    prov = table_provenance(answers, neg + pos, mge.DEV, [a["line"] for a in answers.values()])
    ptab = {"version": POLICY_VERSION, "rule_doc": gcc.rule_verdict.__doc__, "order": [
        "a sure player answer decides (its line and domain fact cited)",
        "an unsure answer: every rotation, reason unsure_pending_player",
        "otherwise the two-flag rule over the key's minimap components: upright when all (or none) read upright; "
        "every rotation when any turns, they disagree (mixed) or the rule cannot read one (undetermined)"],
        "counts": dict(Counter(r["policy"] for r in rows)), "decided_by": dict(Counter(r["decided_by"] for r in rows)),
        "surprises": [r["key"] for r in rows if r["surprise"]], "components": len(comps),
        "provenance": prov, "rows": rows}

    def top1(scores):
        return sum(best_in(scores[r["win_index"]], keys, r["kit"])[0] == r["truth"] for r in pos if r["win_index"] in scores)
    # The instrument, at the widget-scale basis stage 1 measured on: it must reproduce stage 1 (58, 55, 35 of 59).
    kit_keys = sorted({k for r in pos + neg for k in r["kit"]})
    sc_w, _ = key_scores(pos, z, keys, rotating)
    sc_all, _ = key_scores(pos, z, kit_keys, set(kit_keys))
    sc_up, _ = key_scores(pos, z, kit_keys, set())
    s1_widget = top1(sc_w)
    # The tables, at the full transform (widget x map zoom), with the unlabelled discs and the audit null.
    ms_prov = to_map_scale(neg + pos)
    unl, unl_rep = unlabelled_negatives(neg + pos, mge.DEV)
    to_map_scale(unl)
    prov["map_scale"] = ms_prov
    prov["unlabelled_negatives"] = {k: v for k, v in unl_rep.items()}
    negs = neg + unl
    sc, sizes = key_scores(negs + pos, z, keys, rotating)
    ntab = null_table(negs, pos, sc, sizes, keys, policy)
    sc_a, sizes_a = key_scores(negs + pos, z, keys, set(keys))
    aud = audit_null(negs, pos, sc_a, keys)
    for k in keys:
        ntab["keys"][k]["audit_cut"] = aud["keys"][k]
        ntab["keys"][k]["audit_templates"] = {str(s): sizes_a[s][k] for s in sizes_a}
    ntab["banks"]["audit"] = {"n": aud["bank_cut"]["n"], "bank_cut": aud["bank_cut"],
                              "median_key_cut": aud["median_key_cut"]}
    ntab["gate3"] = gate3(ntab)
    ntab["provenance"] = prov
    cut = {k: ntab["keys"][k]["cut"] for k in keys}
    # B2: the labelled-only bank cuts read on the unlabelled discs.
    lab_only = {b: cut_at([best_in(sc[r["win_index"]], keys, r["kit"] if b == "context" else keys)[1]
                           for r in neg if r["win_index"] in sc]) for b in ("context", "full")}
    unl_named = {b: sum(best_in(sc[r["win_index"]], keys, r["kit"] if b == "context" else keys)[1] > lab_only[b]
                        for r in unl if r["win_index"] in sc) for b in lab_only}
    moves = cut_moves(PREV_NULL, ntab, keys)
    right = [r for r in pos if r["win_index"] in sc and best_in(sc[r["win_index"]], keys, r["kit"])[0] == r["truth"]]
    clear = [r for r in right if sc[r["win_index"]][keys.index(r["truth"])] > cut[r["truth"]]]
    rot_cuts = [cut[k] for k in keys if policy[k] == "rotates"]
    up_cuts = [cut[k] for k in keys if policy[k] == "upright"]
    default = {r["key"] for r in rows if r["decided_by"] == NO_COMPONENT}
    up_ev_cuts = [cut[k] for k in keys if policy[k] == "upright" and k not in default]
    bc = {b: ntab["banks"][b]["bank_cut"] for b in ("context", "full")}
    m = {"version": VERSION, "basis": BASIS, "map_scale": ms_prov, "dev_n": len(pos), "negatives_n": len(negs),
         "labelled_negatives_n": len(neg), "unlabelled_negatives_n": len(unl), "unlabelled": unl_rep,
         "b2_labelled_only_bank_cut": {b: round(v, 4) for b, v in lab_only.items()},
         "b2_unlabelled_named_at_labelled_only_cut": unl_named,
         "cut_move": moves,
         "audit": {"bank_cut": aud["bank_cut"], "median_key_cut": aud["median_key_cut"],
                   "median_policy_key_cut": round(float(np.median(list(cut.values()))), 4)},
         "s1_single_policy_widget": s1_widget,
         "s1_single_policy": top1(sc), "control_basis": "widget scale (stage 1's), the instrument check",
         "control_rotate_all": sum(
             best_in(sc_all[r["win_index"]], kit_keys, r["kit"])[0] == r["truth"] for r in pos if r["win_index"] in sc_all),
         "control_upright": sum(
             best_in(sc_up[r["win_index"]], kit_keys, r["kit"])[0] == r["truth"] for r in pos if r["win_index"] in sc_up),
         "control_expected": {"rotate_all": sum(r.get("rot_pred") == r["truth"] for r in pos),
                              "upright": sum(r.get("norot_pred") == r["truth"] for r in pos)},
         "s2_right": len(right), "s2_clear": len(clear), "s2_share": round(len(clear) / max(len(right), 1), 4),
         "s2_not_clear": [f"{r['sid']} {r['t_ms'] / 1000:.2f}s {r['truth']} "
                          f"{sc[r['win_index']][keys.index(r['truth'])]:.3f} <= {cut[r['truth']]:.3f}"
                          for r in right if r not in clear],
         "s3_rotated_keys": len(rot_cuts), "s3_upright_keys": len(up_cuts),
         "s3_median_cut_rotated": round(float(np.median(rot_cuts)), 4),
         "s3_median_cut_upright": round(float(np.median(up_cuts)), 4),
         "s3_gap": round(float(np.median(rot_cuts) - np.median(up_cuts)), 4),
         "s3_upright_keys_with_component": len(up_ev_cuts),
         "s3_median_cut_upright_with_component": round(float(np.median(up_ev_cuts)), 4),
         "no_component_default": len(default),
         "bank_cut": {b: {k: v[k] for k in ("cut", "named", "rate", "per_scale_named", "per_scale_rate",
                                             "glyph_items_named_right_cut", "glyph_items_named_right_per_scale")}
                      | {"by_scale": v["by_scale"]} for b, v in bc.items()},
         "gate3": ntab["gate3"],
         "s1_wrong": [f"{r['sid']} {r['t_ms'] / 1000:.2f}s {r['truth']} -> {best_in(sc[r['win_index']], keys, r['kit'])[0]}"
                      for r in pos if r["win_index"] in sc and r not in right],
         "false_naming": {f"{b}_{w}": ntab["banks"][b][f"false_naming_rate_{w}"] for b in ("context", "full")
                          for w in ("cut", "verdict")},
         "named_right_verdict": {b: ntab["banks"][b]["glyph_items_named_right_verdict"] for b in ("context", "full")},
         "wall_s": round(time.time() - t0, 1)}
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in ((TABLES[0], ptab), (TABLES[1], ntab), ("build.json", m)):
        json.dump(obj, open(out / name, "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({k: v for k, v in m.items() if k not in ("s2_not_clear",)}, indent=1, default=str))
    print("wrote", *[out / n for n in (*TABLES, "build.json")])


def load_tables(out: Path) -> tuple[dict, dict]:
    p, n = (json.load(open(out / t, encoding="utf-8")) for t in TABLES)
    return p, n


# ------------------------------------------------------------------ the follow on dev (S1 follow, S4, pooled null)


class ProposerMemo:
    """Memoise `ability_icons.propose_icons` per crop object while a chunk's crops live, so the follow's arms share
    one proposer run per frame; the follow's behaviour is unchanged. Restores the function on exit."""

    def __enter__(self):
        from reticle import ability_icons
        self.mod, self.fn, self.memo = ability_icons, ability_icons.propose_icons, {}

        def memo(crop, terms, *a, **kw):
            k = (id(crop), id(terms), a, tuple(sorted(kw.items())))
            if k not in self.memo:
                self.memo[k] = (crop, self.fn(crop, terms, *a, **kw))
            return self.memo[k][1]
        ability_icons.propose_icons = memo
        return self

    def clear(self):
        self.memo.clear()

    def __exit__(self, *exc):
        self.mod.propose_icons = self.fn
        self.memo.clear()


def two_hz(ts: list[float], t0: float) -> list[float]:
    """The cached holds nearest t0 + 500 ms x k within the follow window: the ability pass's frames alone."""
    h = np.asarray(ts, float)
    if not len(h):
        return []
    pick = {float(h[np.argmin(np.abs(h - (t0 + TWO_HZ_MS * k)))]) for k in range(int(mge.FOLLOW_MS // TWO_HZ_MS) + 1)}
    return sorted(pick)


ARMS = {"rotate_all_cache": (True, "cache"), "policy_cache": ("policy", "cache"), "policy_2hz": ("policy", "2hz")}


def follow_items(items: list[dict], arms: dict, rotating: set) -> dict:
    """{arm: {win_index: follow result}} for `items`, each arm's rotation and cadence, chunked per session."""
    import cv2
    from reticle import geometry
    mge.ROTATING = {tuple(k.split(":")) for k in rotating}
    res = {a: {} for a in arms}
    by = defaultdict(list)
    for r in items:
        by[r["sid"]].append(r)
    with ProposerMemo() as memo:
        for sid, its in sorted(by.items()):
            c, why, _ = mge.crop_cache(sid)
            x0, y0, x1, y1 = c.rect_of("minimap")
            h = np.asarray(c.holds())
            plan = {r["win_index"]: [float(t) for t in h[(h >= r["t_held"]) & (h <= r["t_held"] + mge.FOLLOW_MS)]]
                    for r in its}
            vis = mge.vision_rows(sid, sorted({t for v in plan.values() for t in v}))
            st = geometry.reference_static(sid, str(mge.STORE))
            static_Y = mge.luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
            for b in range(0, len(its), 12):
                chunk = its[b:b + 12]
                need = sorted({t for r in chunk for t in plan[r["win_index"]]})
                got = {s.t_ms: s.frame[y0:y1, x0:x1].copy() for s in c.samples(need, rois=["minimap"])}
                for r in chunk:
                    ts = [t for t in plan[r["win_index"]] if t in got]
                    first = got[ts[0]]
                    terms = mge.icon_terms(sid, first.shape)
                    sY = static_Y if static_Y.shape == first.shape[:2] else None
                    for a, (rot, cad) in arms.items():
                        mge.FOLLOW_ROTATE = rot
                        use = ts if cad == "cache" else two_hz(ts, r["t_held"])
                        f = mge.follow_item(r, [(t, got[t]) for t in use], vis, terms, sY)
                        res[a][r["win_index"]] = {k: f.get(k) for k in ("pred", "mean", "margin", "decided_by", "n_clean")}
                        res[a][r["win_index"]]["frames"] = len(use)
                memo.clear()
                del got
            print(f"  {sid}: {len(its)} items", flush=True)
    mge.FOLLOW_ROTATE = True
    return res


def cmd_follow(out: Path) -> None:
    gcc.fresh(out / "follow.json")
    t0 = time.time()
    ptab, ntab = load_tables(out)
    rotating = {r["key"] for r in ptab["rows"] if r["policy"] == "rotates"}
    d, z, items = load_dev()
    neg, pos = split_items(items)
    rp = follow_items(pos, ARMS, rotating)
    rn = follow_items(neg, {a: ARMS[a] for a in ("policy_cache", "policy_2hz")}, rotating)
    rep = {"version": VERSION, "follow": mge.FOLLOW_VERSION, "policy_version": ptab["version"], "dev_n": len(pos),
           "negatives_n": len(neg), "arms": {}}
    for a in ARMS:
        R = rp[a]
        right = [r for r in pos if R[r["win_index"]]["pred"] == r["truth"]]
        rep["arms"][a] = {"right": len(right), "n": len(pos), "share": round(len(right) / len(pos), 4),
                          "refused": sum(R[r["win_index"]]["decided_by"] != "follow" for r in pos),
                          "frames_median": float(np.median([R[r["win_index"]]["frames"] for r in pos])),
                          "wrong": [f"{r['sid']} {r['t_ms'] / 1000:.2f}s {r['truth']} -> {R[r['win_index']]['pred']}"
                                    for r in pos if r not in right]}
    rep["s4_points"] = round(100 * (rep["arms"]["policy_2hz"]["share"] - rep["arms"]["policy_cache"]["share"]), 2)
    pooled = {}
    for a in ("policy_cache", "policy_2hz"):
        R = rn[a]
        per = defaultdict(list)
        for r in neg:
            f = R[r["win_index"]]
            if f["decided_by"] == "follow" and f["mean"]:
                for k, v in f["mean"].items():
                    per[k].append(v)
        cuts = {k: {"n": len(v), "cut": round(cut_at(v), 4), **q(v)} for k, v in sorted(per.items())}
        Rp = rp[a]
        right = [r for r in pos if Rp[r["win_index"]]["pred"] == r["truth"]]
        clear = [r for r in right if r["truth"] in cuts and Rp[r["win_index"]]["mean"][r["truth"]] > cuts[r["truth"]]["cut"]]
        named = sum(1 for r in neg if R[r["win_index"]]["decided_by"] == "follow" and
                    R[r["win_index"]]["mean"][R[r["win_index"]]["pred"]] > cuts[R[r["win_index"]]["pred"]]["cut"])
        best = np.array([max(R[r["win_index"]]["mean"].values()) for r in neg
                         if R[r["win_index"]]["decided_by"] == "follow" and R[r["win_index"]]["mean"]])
        bcut = cut_at(best)
        bclear = [r for r in right if Rp[r["win_index"]]["mean"][r["truth"]] > bcut] if bcut is not None else []
        pooled[a] = {"keys": cuts, "negatives_followed": sum(R[r["win_index"]]["decided_by"] == "follow" for r in neg),
                     "false_named_context": named, "right": len(right), "clear": len(clear),
                     "s2_share": round(len(clear) / max(len(right), 1), 4),
                     "bank_cut_context": {"cut": None if bcut is None else round(bcut, 4), "n": int(len(best)),
                                          "named": int((best > bcut).sum()) if bcut is not None else 0,
                                          "rate": round(float((best > bcut).mean()), 4) if bcut is not None else None,
                                          "right_clear": len(bclear),
                                          "s2_share": round(len(bclear) / max(len(right), 1), 4)}}
    rep["pooled_null"] = pooled
    rep["wall_s"] = round(time.time() - t0, 1)
    json.dump(rep, open(out / "follow.json", "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))


# ------------------------------------------------------------------ the thrown-icon seed on the matches (S5)

BIRTH_MS = 1500.0     # a design choice: a thrown icon is born within 1.5 s of the tray drop
BIRTH_R = 2 * mge.OCC_R   # px x scale from the caster, the crowding radius of cross-channel-independence
REF_MS = 500.0        # the reference frame: the ability pass's frame before the drop


def thrown_seed(ref_discs, frames, self_at, vis, terms, kit_keys, scale, static_Y):
    """(t, (x, y), score) of the thrown icon's birth, or (None, reason). A birth is a proposer disc of a frame
    within BIRTH_MS of the drop that no disc of the reference frame (REF_MS before the drop) lies within PRIOR_R x
    scale of; outside the self portrait's cover (OCC_R x scale of the caster, where the follow skips anyway) and
    off any ally icon (SAME_R x scale); within BIRTH_R x scale of the caster; not the baked map; its best kit score
    at least ICON_SCORE. The first frame holding a birth wins; within it, the birth nearest the caster."""
    from reticle import ability_icons
    P = np.array([[q["cx"], q["cy"]] for q in ref_discs], float).reshape(-1, 2)
    for t, crop in frames:
        sx, sy = self_at(t)
        allies = [(x, y) for role, x, y in (vis.get(round(t, 3), (None, []))[1] or []) if role != "self"]
        Y = mge.luma(crop)
        cand = []
        for qd in ability_icons.propose_icons(crop, terms):
            x, y = qd["cx"], qd["cy"]
            dc = float(np.hypot(x - sx, y - sy))
            if len(P) and np.hypot(P[:, 0] - x, P[:, 1] - y).min() <= gcc.PRIOR_R * scale:
                continue
            if dc <= mge.OCC_R * scale or dc > BIRTH_R * scale:
                continue
            if any(np.hypot(ax - x, ay - y) <= mge.SAME_R * scale for ax, ay in allies):
                continue
            if static_Y is not None and mge.map_like(Y, static_Y, (x, y), scale):
                continue
            s = mge.frame_scores(Y, (x, y), scale, kit_keys)
            if s is not None and s.max() >= mge.ICON_SCORE:
                cand.append((dc, x, y, float(s.max())))
        if cand:
            dc, x, y, s = min(cand)
            return t, (float(x), float(y)), s
    return None, "no_thrown_birth"


def paired(rows: list[dict], arm: str = "rotate_all") -> dict:
    """The self seed's stored outcome on the casts the thrown seed (`arm`) named, and the two seeds' outcomes where
    both named: does the thrown seed fix the casts the self seed got wrong?"""
    named = [x for x in rows if (x.get(arm) or {}).get("outcome") in ("right", "wrong")]
    selfc = Counter(x["self_seed"] for x in named)
    both = [x for x in named if x["self_seed"] in ("right", "wrong")]
    pair = Counter(f"self_{x['self_seed']}__thrown_{x[arm]['outcome']}" for x in both)
    return {"arm": arm, "thrown_named": len(named), "self_right": selfc["right"], "self_wrong": selfc["wrong"],
            "self_refused": selfc["refused"],
            "self_precision": round(selfc["right"] / (selfc["right"] + selfc["wrong"]), 4)
            if selfc["right"] + selfc["wrong"] else None,
            "both_named": len(both), "both_right": pair["self_right__thrown_right"],
            "both_wrong": pair["self_wrong__thrown_wrong"], "self_only_right": pair["self_right__thrown_wrong"],
            "thrown_only_right": pair["self_wrong__thrown_right"]}


def cmd_thrown(out: Path, only: set | None = None) -> None:
    """S5: on the matches' own glyph casts (cross-channel-independence-0.1.0 casts.jsonl, `B_source` glyph), the
    follow seeded at the thrown icon's birth; rotate-all (the self seed's arm) and the policy table's rotations.
    S5 is scored on the rotate-all arm, whose only change from the stored self-seed run is the seed; the policy
    arm reports beside it. Precision is right over named, as `glyph_channel_cost.cmd_crosscheck` counts it."""
    gcc.fresh(out / "thrown.json")
    import cv2
    import cross_channel_independence as cci
    from reticle import ability_icons, ability_shapes, geometry
    from reticle.store import Store
    t0 = time.time()
    ptab, _ = load_tables(out)
    rotating = {tuple(r["key"].split(":")) for r in ptab["rows"] if r["policy"] == "rotates"}
    rows = [json.loads(ln) for ln in open(gcc.CROSS_CASTS, encoding="utf-8") if ln.strip()]
    casts = [r for r in rows if r["kind"] == "match" and r["B_source"] == "glyph" and (not only or r["sid"] in only)]
    store = Store(str(mge.STORE))
    arms = {"rotate_all": True, "policy": "policy"}
    res = []
    by = defaultdict(list)
    for i, r in enumerate(casts):
        by[r["sid"]].append(i)
    with ProposerMemo() as memo:
        for sid, ix in sorted(by.items()):
            c, why, _ = mge.crop_cache(sid)
            if c is None:
                res += [{"i": i, "refused": f"no_crop_cache:{why}"} for i in ix]
                continue
            x0, y0, x1, y1 = c.rect_of("minimap")
            h = np.asarray(c.holds())
            track = cci.self_seed_track(store, sid)
            try:
                st = geometry.reference_static(sid, str(mge.STORE))
                static_Y = mge.luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
            except (SystemExit, Exception):  # noqa: BLE001
                static_Y = None
            for i in ix:
                memo.clear()                      # the last cast's crops leave with their memo
                r = casts[i]
                ts = [float(t) for t in h[(h >= r["t_ms"] - 1e-6) & (h <= r["t_ms"] + mge.FOLLOW_MS)]]
                before = h[h < r["t_ms"] - 1e-6]
                if not ts or not len(before):
                    res.append({"i": i, "refused": "no_cached_frame"})
                    continue
                ref_t = float(before[np.argmin(np.abs(before - (r["t_ms"] - REF_MS)))])
                need = sorted({ref_t, *ts})
                vis = mge.vision_rows(sid, need)
                got = {s.t_ms: s.frame[y0:y1, x0:x1].copy() for s in c.samples(need, rois=["minimap"])}
                ts = [t for t in ts if t in got]
                if not ts or ref_t not in got:
                    res.append({"i": i, "refused": "no_cached_frame"})
                    continue
                first = got[ts[0]]
                scale = first.shape[1] / 465.0
                seed = ability_shapes.seed_from_track(*track, r["t_ms"]) if track is not None else None
                if seed is None:
                    for t in ts[:4]:
                        sel = [(x, y) for role, x, y in (vis.get(round(t, 3), (None, []))[1] or []) if role == "self"]
                        if sel:
                            seed = sel[0]
                            break
                if seed is None:
                    res.append({"i": i, "refused": "no_self_seed"})
                    continue

                def self_at(t, seed=seed, vis=vis):
                    sel = [(x, y) for role, x, y in (vis.get(round(t, 3), (None, []))[1] or []) if role == "self"]
                    return sel[0] if sel else seed
                terms = mge.icon_terms(sid, first.shape)
                sY = static_Y if static_Y is not None and static_Y.shape == first.shape[:2] else None
                kit_keys = tuple(sorted(mge.kit(r["agent"])))
                mge.FOLLOW_ROTATE = True
                if terms is None:
                    bt, bp = None, "no_slab_terms"
                else:
                    bt, bp = thrown_seed(ability_icons.propose_icons(got[ref_t], terms),
                                         [(t, got[t]) for t in ts if t <= r["t_ms"] + BIRTH_MS], self_at, vis, terms,
                                         kit_keys, scale, sY)[:2]
                row = {"i": i, "sid": sid, "t_ms": r["t_ms"], "agent": r["agent"], "slot": r["slot"],
                       "self_seed": r["glyph"], "self_seed_pred": (r.get("glyph_follow") or {}).get("pred")}
                if bt is None:
                    row["refused"] = bp
                else:
                    row.update(birth_t=bt, birth_dt_ms=round(bt - r["t_ms"], 1), birth=list(bp),
                               birth_from_self=round(float(np.hypot(bp[0] - self_at(bt)[0], bp[1] - self_at(bt)[1]) / scale), 2))
                    item = {"kit": [f"{k[0]}:{k[1]}" for k in kit_keys], "scale": scale, "cx": bp[0], "cy": bp[1],
                            "t_held": bt}
                    for a, rot in arms.items():
                        mge.FOLLOW_ROTATE = rot
                        mge.ROTATING = rotating
                        f = mge.follow_item(item, [(t, got[t]) for t in ts if t >= bt], vis, terms, sY)
                        pred = f.get("pred") if f["decided_by"] == "follow" else None
                        row[a] = {"pred": pred, "decided_by": f["decided_by"], "n_clean": f["n_clean"],
                                  "margin": f.get("margin"),
                                  "outcome": "refused" if pred is None else
                                  ("right" if pred.rsplit(":", 1)[1] == r["slot"] else "wrong")}
                res.append(row)
                memo.clear()
                del got
            print(f"  {sid}: {len(ix)} casts, {time.time() - t0:.0f}s", flush=True)
    mge.FOLLOW_ROTATE = True
    summ = {}
    for a in arms:
        oc = Counter((x.get(a) or {}).get("outcome", "refused") for x in res)
        summ[a] = {"right": oc["right"], "wrong": oc["wrong"], "refused": oc["refused"],
                   "precision": round(oc["right"] / (oc["right"] + oc["wrong"]), 4) if oc["right"] + oc["wrong"] else None}
    selfc = Counter(r["glyph"] for r in casts)
    summ["self_seed_stored"] = {"right": selfc["right"], "wrong": selfc["wrong"], "refused": selfc["refused"],
                                "precision": round(selfc["right"] / (selfc["right"] + selfc["wrong"]), 4)}
    summ["paired"] = paired(res)
    summ["refusals"] = dict(Counter(x["refused"] for x in res if x.get("refused")))
    summ["by_key"] = {}
    for x in res:
        if "rotate_all" in x:
            k = f"{x['agent']}:{x['slot']}"
            summ["by_key"].setdefault(k, Counter())[x["rotate_all"]["outcome"]] += 1
    rep = {"version": VERSION, "casts": str(gcc.CROSS_CASTS), "n": len(casts), "only": sorted(only) if only else None,
           "params": {
        "BIRTH_MS": BIRTH_MS, "BIRTH_R": BIRTH_R, "REF_MS": REF_MS, "PRIOR_R": gcc.PRIOR_R, "OCC_R": mge.OCC_R,
        "SAME_R": mge.SAME_R, "follow": mge.FOLLOW_VERSION}, "summary": summ, "rows": res,
        "wall_s": round(time.time() - t0, 1)}
    json.dump(rep, open(out / "thrown.json", "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps(summ, indent=1, default=str))


# ------------------------------------------------------------------ the reference bank the stage 2 reader reads

#: 0.2.0: each source's game file (path under the export, sha256) beside its provenance; the glyphs are 0.1.0's.
#: 0.3.0: pairs with glyph-null-table-0.2.0 (the full transform); the glyphs are 0.1.0's.
#: 0.3.1: pairs with glyph-rotation-policy-0.1.2 and glyph-null-table-0.2.1; the glyphs are 0.1.0's.
BANK_VERSION = "glyph-bank-0.3.1"


def source_files(sources: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(game file under the export, its sha256) of each (key, provenance) source: the DisplayIcon's png, an
    answer's file, or a correlation or game-data marker's png found by its unique name under the export."""
    index: dict = {}
    for f in mge.GX.rglob("*.png"):
        index.setdefault(f.name, []).append(f)
    out = []
    for key, prov in sources:
        kind, _, rest = prov.partition(":")
        if kind == "icon":
            f = Path(mge.GLYPHS[tuple(key.split(":"))]["file"])
        elif kind == "answer":
            f = mge.GX / rest.split(":", 1)[1]
        else:                                        # "1306:<name> corr .." and "gamedata:<name> <inv> <row>"
            name = rest.split(" ")[0]
            hits = index.get(name) or index.get(name + ".png") or []
            if len(hits) != 1:
                raise SystemExit(f"{key} {prov!r}: {len(hits)} export files named {name}")
            f = hits[0]
        f = f.resolve()
        out.append((f.relative_to(mge.GX.resolve()).as_posix(), sha256(f)))
    return out


def cmd_bank(out: Path, tables: Path) -> None:
    """Write the references the tables in `tables` were built on as versioned data (`glyph-bank-0.3.1.npz` and
    `.json` under `out`): every catalogue key's 128 px glyphs, one per source (the DisplayIcon, then each export
    texture the eval 0.3.0 dev run assigned it: correlation, the state inventory's minimap brushes and the player's
    texture answers, `load_dev`). `reticle.minimap_glyph` reads this file and never imports this script. Refuses
    when the answers file has moved since the tables were built."""
    for n in (f"{BANK_VERSION}.npz", f"{BANK_VERSION}.json"):
        gcc.fresh(out / n)
    ptab, ntab = load_tables(tables)
    have = sha256(mge.ANSWERS)
    if have != ptab["provenance"]["answers"]["sha256"]:
        raise SystemExit(f"answers moved since {ptab['version']} was built ({have}); rebuild the tables first")
    load_dev()                                       # the references the dev run, and so the tables, used
    keys = catalogue_keys()
    glyphs, owner, prov = [], [], []
    for k in keys:
        for name, g in mge.sources(tuple(k.split(":"))):
            glyphs.append(np.asarray(g, np.float32))
            owner.append(k)
            prov.append(name)
    G = np.stack(glyphs)
    files = source_files(list(zip(owner, prov)))
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"{BANK_VERSION}.npz", glyphs=G, keys=np.array(owner), provenance=np.array(prov),
                        files=np.array([f for f, _ in files]), file_sha256=np.array([h for _, h in files]))
    meta = {"version": BANK_VERSION, "generator": VERSION, "eval": mge.VERSION, "build": mge.BUILD,
            "glyph_px": int(G.shape[1]), "keys": len(keys), "sources": len(owner),
            "glyphs_sha256": hashlib.sha256(G.tobytes()).hexdigest(),
            "npz_sha256": sha256(out / f"{BANK_VERSION}.npz"),
            "matcher": {"canvas_base": [float(c) for c in mge.CANVAS], "mask_r_base": mge.MASK_R,
                        "shift_base": mge.SHIFT, "rotations": list(mge.ROTS), "scale": "geometry.MapScale.scale (widget x map zoom)",
                        "resample": "INTER_AREA to shrink the 128 px glyph to the canvas, INTER_LINEAR to turn"},
            "references": {"states": "probe", "answers": True, "gamedata": True,
                           "answers_file": str(mge.ANSWERS), "answers_sha256": have,
                           "state_inventory": str(mge.STATE_INVENTORY),
                           "state_inventory_sha256": sha256(mge.STATE_INVENTORY),
                           "game_files": str(mge.GX)},
            "tables": {"dir": str(tables), "policy": ptab["version"], "null": ntab["version"],
                       "policy_sha256": sha256(tables / TABLES[0]), "null_sha256": sha256(tables / TABLES[1])},
            "per_key_sources": dict(Counter(owner)),
            "sources": [{"key": k, "provenance": pv, "file": f, "sha256": h}
                        for k, pv, (f, h) in zip(owner, prov, files)]}
    json.dump(meta, open(out / f"{BANK_VERSION}.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v for k, v in meta.items() if k not in ("per_key_sources", "sources")}, indent=1))


# ------------------------------------------------------------------ metric series


def cmd_record(out: Path) -> None:
    """Record build.json, follow.json and thrown.json under `out` as glyph_tables/* metric series, once."""
    from reticle import metrics
    if gcc.recorded("s1", "run", str(out)) or any(r.get("tool") == "glyph_tables" and
                                                  (r.get("context") or {}).get("run") == str(out) for r in metrics.load()):
        raise SystemExit(f"{out} is already recorded")
    ptab, ntab = load_tables(out)
    b = json.load(open(out / "build.json", encoding="utf-8"))
    deps = {"version": VERSION, "policy": ptab["version"], "null": ntab["version"], "eval": mge.VERSION,
            "build": mge.BUILD, "answers_sha256": ptab["provenance"]["answers"]["sha256"]}
    ctx = {"run": str(out), "dev_sessions": ",".join(ptab["provenance"]["dev_sessions"])}
    metrics.record("glyph_tables", part="policy", values={
        "keys": len(ptab["rows"]), "rotates": ptab["counts"].get("rotates", 0),
        "upright": ptab["counts"].get("upright", 0),
        "by_answer": ptab["decided_by"].get("player_answer", 0), "unsure": ptab["decided_by"].get(UNSURE, 0),
        "by_rule": ptab["decided_by"].get("two_flag_rule", 0), "no_component_default": ptab["decided_by"].get(NO_COMPONENT, 0),
        "surprises": len(ptab["surprises"])},
        deps=deps, context=ctx)
    metrics.record("glyph_tables", part="build", values={
        k: b[k] for k in ("dev_n", "negatives_n", "s1_single_policy", "control_rotate_all", "control_upright",
                          "s2_right", "s2_clear", "s2_share", "s3_rotated_keys", "s3_upright_keys",
                          "s3_median_cut_rotated", "s3_median_cut_upright", "s3_gap")} |
        {f"false_naming_{k}": v for k, v in b["false_naming"].items()} |
        {f"named_right_verdict_{k}": v for k, v in b["named_right_verdict"].items()} |
        {k: b[k] for k in ("s3_upright_keys_with_component", "s3_median_cut_upright_with_component")} |
        {f"bank_cut_{bk}_{k}": v[k] for bk, v in b["bank_cut"].items()
         for k in ("cut", "named", "rate", "per_scale_rate", "glyph_items_named_right_cut",
                   "glyph_items_named_right_per_scale")} |
        {f"bank_cut_{bk}_scale_{sk.replace('.', 'p')}_{k}": sv[k] for bk, v in b["bank_cut"].items()
         for sk, sv in v["by_scale"].items() for k in ("n", "cut")},
        deps=deps, context=ctx,
        controls=[{"name": "rotate-all reproduces the eval 0.3.0 dev rot_pred (55/59)",
                   "observed": b["control_rotate_all"], "expected": b["control_expected"]["rotate_all"], "tol": 0},
                  {"name": "upright reproduces the eval 0.3.0 dev norot_pred (35/59)",
                   "observed": b["control_upright"], "expected": b["control_expected"]["upright"], "tol": 0}])
    if (out / "follow.json").exists():
        f = json.load(open(out / "follow.json", encoding="utf-8"))
        v = {f"{a}_right": f["arms"][a]["right"] for a in f["arms"]} | {"dev_n": f["dev_n"], "s4_points": f["s4_points"]}
        for a, p in f["pooled_null"].items():
            v |= {f"pooled_{a}_s2_share": p["s2_share"], f"pooled_{a}_clear": p["clear"], f"pooled_{a}_right": p["right"],
                  f"pooled_{a}_false_named": p["false_named_context"], f"pooled_{a}_negatives": p["negatives_followed"]}
            v |= {f"pooled_{a}_bank_cut_context_{k}": p["bank_cut_context"][k] for k in ("cut", "named", "rate", "s2_share")}
        metrics.record("glyph_tables", part="follow", values=v, deps=deps | {"follow": f["follow"]}, context=ctx,
                       controls=[{"name": "rotate-all follow reproduces minimap_glyph_eval/killjoy_refs_dev (58/59)",
                                  "observed": f["arms"]["rotate_all_cache"]["right"], "expected": 58, "tol": 0}])
    if (out / "thrown.json").exists():
        t = json.load(open(out / "thrown.json", encoding="utf-8"))["summary"]
        v = {f"{a}_{k}": t[a][k] for a in ("rotate_all", "policy", "self_seed_stored")
             for k in ("right", "wrong", "refused", "precision")}
        v |= {f"paired_{k}": val for k, val in t["paired"].items() if k != "arm"}
        metrics.record("glyph_tables", part="thrown", session="matches", values=v, deps=deps,
                       context=ctx | {"casts": str(gcc.CROSS_CASTS)},
                       controls=[{"name": "stored self seed precision (glyph_channel_cost/cross_channel@matches)",
                                  "observed": t["self_seed_stored"]["precision"], "expected": 0.5798, "tol": 0}])
    print(metrics.report(tool="glyph_tables"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("build", "follow", "thrown", "record", "bank"))
    ap.add_argument("--out", required=True, help="the run's directory; build creates it")
    ap.add_argument("--only", default=None, help="thrown: a sample of sessions (sid,sid), never the S5 run")
    ap.add_argument("--tables", default=None, help="bank: the directory holding the tables it pairs with")
    a = ap.parse_args()
    out = Path(a.out)
    if a.cmd == "bank":
        if not a.tables:
            raise SystemExit("bank needs --tables <the build's directory>")
        cmd_bank(out, Path(a.tables))
        return
    if a.cmd == "thrown":
        cmd_thrown(out, set(a.only.split(",")) if a.only else None)
        return
    {"build": cmd_build, "follow": cmd_follow, "record": cmd_record}[a.cmd](out)


if __name__ == "__main__":
    main()
